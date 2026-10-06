import { createMockJobQueue } from '~/tests/helpers/mocks/job-queue.mock'
import { MockKafkaProducerWrapper } from '~/tests/helpers/mocks/producer.mock'
import { mockFetch } from '~/tests/helpers/mocks/request.mock'

import { Message } from 'node-rdkafka'

import { KAFKA_CDP_EVENTS_DLQ, KAFKA_EVENTS_JSON } from '~/common/config/kafka-topics'
import { KafkaConsumer } from '~/common/kafka/consumer/consumer-v1'
import { KafkaProducerWrapper } from '~/common/kafka/producer'
import { closeHub, createHub } from '~/common/utils/db/hub'
import { PostgresUse } from '~/common/utils/db/postgres'
import { createCdpConsumerDeps } from '~/tests/helpers/cdp'
import { waitForExpect } from '~/tests/helpers/expectations'
import { TEST_KAFKA_TOPICS, createKafkaTestTopicName, ensureKafkaTopics } from '~/tests/helpers/kafka'
import { getFirstTeam, resetTestDatabase } from '~/tests/helpers/sql'

import { Hub, Team } from '../../types'
import { FixtureHogFlowBuilder } from '../_tests/builders/hogflow.builder'
import { HOG_EXAMPLES, HOG_FILTERS_EXAMPLES, HOG_INPUTS_EXAMPLES } from '../_tests/examples'
import { createIncomingEvent, insertHogFunction } from '../_tests/fixtures'
import { insertHogFlow } from '../_tests/fixtures-hogflows'
import { CdpCyclotronWorker } from '../consumers/cdp-cyclotron-worker.consumer'
import { CdpEventsConsumer } from '../consumers/cdp-events.consumer'
import { CyclotronJobQueueKafka } from '../services/job-queue/job-queue-kafka'
import { CyclotronJobQueuePostgresV2 } from '../services/job-queue/job-queue-postgres-v2'
import { JobQueue } from '../services/job-queue/job-queue.interface'
import { HogFunctionType } from '../types'
import { ReplayPartitionInput, ReplayPartitionResult, replayPartition } from './activities'
import { CdpDlqReplayer } from './cdp-dlq-replayer'
import { DlqPartitionReader } from './partition-reader'

const ActualKafkaProducerWrapper = jest.requireActual('~/common/kafka/producer').KafkaProducerWrapper

// Truncated bytecode: resolving this input throws, the way a narrowed builtin arity did.
const BROKEN_INPUTS: HogFunctionType['inputs'] = {
    url: { order: 0, value: 'https://example.com', bytecode: ['_H', 1, 2] },
}

describe('CDP dead-letter replay', () => {
    jest.setTimeout(60000)

    let hub: Hub
    let team: Team
    let kafkaProducer: KafkaProducerWrapper
    let eventsConsumer: CdpEventsConsumer | undefined
    let replayer: CdpDlqReplayer | undefined
    let cyclotronWorker: CdpCyclotronWorker | undefined
    let dlqTopic: string
    let eventsTopic: string
    let readCount: number

    beforeEach(async () => {
        MockKafkaProducerWrapper.create = jest.fn((...args) => ActualKafkaProducerWrapper.create(...args))

        // Both topics are per test. Topics are not deleted between runs, so a shared one would
        // hand each run everything every earlier run produced and there would be nothing to assert.
        dlqTopic = createKafkaTestTopicName(KAFKA_CDP_EVENTS_DLQ)
        eventsTopic = createKafkaTestTopicName(KAFKA_EVENTS_JSON)
        readCount = 0
        await ensureKafkaTopics([...TEST_KAFKA_TOPICS, dlqTopic, eventsTopic])
        await resetTestDatabase()

        hub = await createHub()
        hub.CDP_DLQ_ENABLED = true
        hub.CDP_EVENTS_DLQ_TOPIC = dlqTopic
        kafkaProducer = await ActualKafkaProducerWrapper.create(hub.KAFKA_CLIENT_RACK)
        team = await getFirstTeam(hub.postgres)
    })

    afterEach(async () => {
        await Promise.all([eventsConsumer?.stop(), replayer?.stop(), cyclotronWorker?.stop()])
        eventsConsumer = undefined
        replayer = undefined
        cyclotronWorker = undefined
        await kafkaProducer.disconnect()
        await closeHub(hub)
    })

    /**
     * Starts the real events consumer against this test's own events topic.
     *
     * Its own topic and group, so the events one test produces are not read by another, and so a
     * group that has never committed still sees a record produced after it connects.
     */
    const startEventsConsumer = async (queues: { hogQueue: JobQueue; hogflowQueue: JobQueue }): Promise<void> => {
        eventsConsumer = new CdpEventsConsumer(
            hub,
            createCdpConsumerDeps(hub, kafkaProducer),
            queues,
            eventsTopic,
            `e2e-events-${eventsTopic}`
        )
        await eventsConsumer.start()
    }

    /**
     * Produces an event and waits for the consumer to park it.
     *
     * Nothing here calls the consumer's own methods. The record has to arrive because the consumer
     * read the event, failed to build it, and wrote the record itself, which is the half of the
     * loop these tests would otherwise take on trust.
     */
    const parkEvent = async (expected = 1): Promise<Message[]> => {
        const event = createIncomingEvent(team.id, {})
        await kafkaProducer.produce({
            topic: eventsTopic,
            value: Buffer.from(JSON.stringify(event)),
            key: Buffer.from(event.uuid),
        })
        await kafkaProducer.flush()
        return await readDlqRecords(expected)
    }

    /** Stands in for the forward fix: the same function, with inputs that now resolve. */
    const repairInputs = async (fn: HogFunctionType): Promise<void> => {
        await hub.postgres.query(
            PostgresUse.COMMON_WRITE,
            `UPDATE posthog_hogfunction SET inputs = $1 WHERE id = $2`,
            [JSON.stringify(HOG_INPUTS_EXAMPLES.simple_fetch.inputs), fn.id],
            'repair-hog-function-inputs'
        )
    }

    /** Reads the parked records back off the topic, waiting until the consumer has produced them. */
    const readDlqRecords = async (expected = 1): Promise<Message[]> => {
        const consumer = new KafkaConsumer(
            {
                topic: dlqTopic,
                groupId: `e2e-read-${dlqTopic}-${++readCount}`,
                autoCommit: false,
                autoOffsetStore: false,
            },
            { 'auto.offset.reset': 'earliest' } as never
        )
        const messages: Message[] = []
        await consumer.connect((batch) => {
            messages.push(...batch)
            return Promise.resolve()
        })
        await waitForExpect(() => expect(messages.length).toBeGreaterThanOrEqual(expected), 30000)
        await consumer.disconnect()
        return messages
    }

    const runReplay = async (
        queues: { hogQueue: JobQueue; hogflowQueue: JobQueue },
        input: Partial<ReplayPartitionInput> = {},
        heartbeatDetails?: ReplayPartitionResult
    ): Promise<ReplayPartitionResult> => {
        replayer = new CdpDlqReplayer(hub, createCdpConsumerDeps(hub, kafkaProducer), queues)
        return await replayPartition(
            { replayer, openReader: () => DlqPartitionReader.open(), defaultTopic: dlqTopic },
            {
                topic: dlqTopic,
                partition: 0,
                start_timestamp_ms: 0,
                end_timestamp_ms: Date.now() + 60_000,
                ...input,
            },
            { heartbeat: () => {}, heartbeatDetails, cancellationSignal: new AbortController().signal }
        )
    }

    /** Stands in for the forward fix on the filter side. */
    const repairFilters = async (fn: HogFunctionType): Promise<void> => {
        await hub.postgres.query(
            PostgresUse.COMMON_WRITE,
            `UPDATE posthog_hogfunction SET filters = $1 WHERE id = $2`,
            [JSON.stringify(HOG_FILTERS_EXAMPLES.no_filters.filters), fn.id],
            'repair-hog-function-filters'
        )
    }

    it('parks an event that cannot build, then rebuilds only that function after the fix', async () => {
        const broken = await insertHogFunction(hub.postgres, team.id, {
            ...HOG_EXAMPLES.simple_fetch,
            ...HOG_FILTERS_EXAMPLES.no_filters,
            type: 'destination',
            inputs_schema: [{ key: 'url', type: 'string', label: 'Webhook URL', required: true }],
            inputs: BROKEN_INPUTS,
        })
        const healthy = await insertHogFunction(hub.postgres, team.id, {
            ...HOG_EXAMPLES.simple_fetch,
            ...HOG_INPUTS_EXAMPLES.simple_fetch,
            ...HOG_FILTERS_EXAMPLES.no_filters,
            type: 'destination',
        })

        // --- park -------------------------------------------------------------------------
        const sourceQueue = createMockJobQueue()
        await startEventsConsumer({ hogQueue: sourceQueue, hogflowQueue: sourceQueue })

        await parkEvent()

        // The healthy function delivered on the first pass. That is what the replay must not repeat.
        expect(sourceQueue.queueInvocations).toHaveBeenCalledWith([expect.objectContaining({ functionId: healthy.id })])

        // --- fix, then replay -------------------------------------------------------------
        await repairInputs(broken)

        const replayQueue = createMockJobQueue()
        const result = await runReplay({ hogQueue: replayQueue, hogflowQueue: replayQueue })

        // Only the parked function was rebuilt: every invocation the replay queued is that one.
        const replayed = replayQueue.queueInvocations.mock.calls.flatMap(([invocations]: [any[]]) => invocations)
        expect(replayed.map((invocation: any) => invocation.functionId)).toEqual([broken.id])
        expect(replayed[0].queueMetadata).toMatchObject({ replayed_from_dlq: true })
        expect(result).toMatchObject({ records_read: 1, records_in_scope: 1, invocations_queued: 1, blocked: null })
    })

    it('rebuilds each function once when one event is parked twice', async () => {
        // A record is written per event and per step, so an event that fails the filter for one
        // function and the inputs for another is parked twice. Both records name the same event.
        const brokenFilter = await insertHogFunction(hub.postgres, team.id, {
            ...HOG_EXAMPLES.simple_fetch,
            ...HOG_INPUTS_EXAMPLES.simple_fetch,
            ...HOG_FILTERS_EXAMPLES.broken_filters,
            type: 'destination',
        })
        const brokenInputs = await insertHogFunction(hub.postgres, team.id, {
            ...HOG_EXAMPLES.simple_fetch,
            ...HOG_FILTERS_EXAMPLES.no_filters,
            type: 'destination',
            inputs_schema: [{ key: 'url', type: 'string', label: 'Webhook URL', required: true }],
            inputs: BROKEN_INPUTS,
        })

        const sourceQueue = createMockJobQueue()
        await startEventsConsumer({ hogQueue: sourceQueue, hogflowQueue: sourceQueue })

        await parkEvent(2)

        await repairInputs(brokenInputs)
        await repairFilters(brokenFilter)

        const replayQueue = createMockJobQueue()
        const result = await runReplay({ hogQueue: replayQueue, hogflowQueue: replayQueue })
        expect(result.invocations_queued).toBe(2)

        // Both parked functions come back, each exactly once, through the activity's own read of
        // the partition. The case below covers the same union with the records passed in directly.
        const replayed = replayQueue.queueInvocations.mock.calls.flatMap(([invocations]: [any[]]) => invocations)
        expect(replayed.map((invocation: any) => invocation.functionId).sort()).toEqual(
            [brokenFilter.id, brokenInputs.id].sort()
        )
    })

    it('sends the delivery for real: parked, fixed, replayed, and the destination is called', async () => {
        // Everything else here stops once an invocation is queued. This one runs the invocation
        // through cyclotron as well, so the whole loop is covered: the event fails to build, the
        // bytes land on a real topic, the replay reads them back, the invocation is
        // rebuilt, and the destination is actually called.
        const broken = await insertHogFunction(hub.postgres, team.id, {
            ...HOG_EXAMPLES.simple_fetch,
            ...HOG_FILTERS_EXAMPLES.no_filters,
            type: 'destination',
            inputs_schema: HOG_INPUTS_EXAMPLES.simple_fetch.inputs_schema,
            inputs: { ...HOG_INPUTS_EXAMPLES.simple_fetch.inputs, ...BROKEN_INPUTS },
        })

        const kafkaQueue = new CyclotronJobQueueKafka(hub.KAFKA_CLIENT_RACK, hub, hub.CONSUMER_BATCH_SIZE)
        const postgresQueue = new CyclotronJobQueuePostgresV2(hub.CONSUMER_BATCH_SIZE, hub)

        await startEventsConsumer({ hogQueue: kafkaQueue, hogflowQueue: postgresQueue })

        await parkEvent()

        // Nothing was delivered: the only destination on this event could not be built.
        expect(mockFetch).not.toHaveBeenCalled()

        // The forward fix, then the replay, with cyclotron running to execute what it queues.
        await repairInputs(broken)
        cyclotronWorker = new CdpCyclotronWorker(hub, createCdpConsumerDeps(hub, kafkaProducer), kafkaQueue)
        await cyclotronWorker.start()

        await Promise.all([kafkaQueue.startAsProducer(), postgresQueue.startAsProducer()])
        await runReplay({ hogQueue: kafkaQueue, hogflowQueue: postgresQueue })

        await waitForExpect(() => {
            expect(mockFetch).toHaveBeenCalledTimes(1)
        }, 30000)

        expect(mockFetch.mock.calls[0][0]).toBe('https://example.com/posthog-webhook')
    }, 60000)

    it('rebuilds one event once when both its records arrive in the same batch', async () => {
        // Batch size is the deployment's, so two records for one event can land together. Without
        // the union the second record's targets overwrite the first's: one destination is never
        // replayed and the event is rebuilt twice, queueing the other one twice.
        const brokenFilter = await insertHogFunction(hub.postgres, team.id, {
            ...HOG_EXAMPLES.simple_fetch,
            ...HOG_INPUTS_EXAMPLES.simple_fetch,
            ...HOG_FILTERS_EXAMPLES.broken_filters,
            type: 'destination',
        })
        const brokenInputs = await insertHogFunction(hub.postgres, team.id, {
            ...HOG_EXAMPLES.simple_fetch,
            ...HOG_FILTERS_EXAMPLES.no_filters,
            type: 'destination',
            inputs_schema: [{ key: 'url', type: 'string', label: 'Webhook URL', required: true }],
            inputs: BROKEN_INPUTS,
        })

        const sourceQueue = createMockJobQueue()
        await startEventsConsumer({ hogQueue: sourceQueue, hogflowQueue: sourceQueue })
        const records = await parkEvent(2)
        expect(records).toHaveLength(2)

        await repairInputs(brokenInputs)
        await repairFilters(brokenFilter)

        const replayQueue = createMockJobQueue()
        replayer = new CdpDlqReplayer(hub, createCdpConsumerDeps(hub, kafkaProducer), {
            hogQueue: replayQueue,
            hogflowQueue: replayQueue,
        })
        await replayer.replayBatch(records)

        const queued = replayQueue.queueInvocations.mock.calls.flatMap(([invocations]: [any[]]) => invocations)
        expect(queued.map((invocation: any) => invocation.functionId).sort()).toEqual(
            [brokenFilter.id, brokenInputs.id].sort()
        )
    })

    it('does not re-send a destination when only the workflow pipeline threw', async () => {
        // Both pipelines run against the same event. If destinations build and queue while the
        // workflow pipeline throws, the record names no id — and without the kind on it a replay
        // would rebuild the destinations that already delivered.
        const healthy = await insertHogFunction(hub.postgres, team.id, {
            ...HOG_EXAMPLES.simple_fetch,
            ...HOG_INPUTS_EXAMPLES.simple_fetch,
            ...HOG_FILTERS_EXAMPLES.no_filters,
            type: 'destination',
        })

        const sourceQueue = createMockJobQueue()
        await startEventsConsumer({ hogQueue: sourceQueue, hogflowQueue: sourceQueue })

        // Only the workflow side throws, so the destination is built and delivered as normal. The
        // executor rather than the pipeline, so the pipeline's own catch is what handles it.
        jest.spyOn(eventsConsumer!['hogFlowExecutor'], 'buildHogFlowInvocations').mockRejectedValue(
            new Error('workflow builder walked off a cliff')
        )

        const records = await parkEvent()
        expect(records).toHaveLength(1)

        // The destination built and delivered on the first pass, while the workflow side threw.
        expect(sourceQueue.queueInvocations).toHaveBeenCalledWith([expect.objectContaining({ functionId: healthy.id })])

        const replayQueue = createMockJobQueue()
        replayer = new CdpDlqReplayer(hub, createCdpConsumerDeps(hub, kafkaProducer), {
            hogQueue: replayQueue,
            hogflowQueue: replayQueue,
        })
        await replayer.replayBatch(records)

        // The record names hog_flow, so the destination that already delivered is not rebuilt.
        const queued = replayQueue.queueInvocations.mock.calls.flatMap(([invocations]: [any[]]) => invocations)
        expect(queued.map((invocation: any) => invocation.functionId)).not.toContain(healthy.id)
    })

    it('stops at a destination that still fails to build, then picks up there after the fix', async () => {
        // The fix is not deployed yet. A filter or input that throws is handled per function, so
        // the rebuild comes back as an empty invocation list and no error. The replay has to read
        // that as a failed replay, or it moves past a delivery that never happened.
        const broken = await insertHogFunction(hub.postgres, team.id, {
            ...HOG_EXAMPLES.simple_fetch,
            ...HOG_FILTERS_EXAMPLES.no_filters,
            type: 'destination',
            inputs_schema: [{ key: 'url', type: 'string', label: 'Webhook URL', required: true }],
            inputs: BROKEN_INPUTS,
        })

        const sourceQueue = createMockJobQueue()
        await startEventsConsumer({ hogQueue: sourceQueue, hogflowQueue: sourceQueue })
        await parkEvent()

        const replayQueue = createMockJobQueue()
        const blocked = await runReplay({ hogQueue: replayQueue, hogflowQueue: replayQueue })
        expect(blocked).toMatchObject({ next_offset: 0, blocked: { offset: 0 } })
        expect(blocked.blocked!.error).toContain('still fail to build')
        expect(replayQueue.queueInvocations).not.toHaveBeenCalled()

        // With the fix applied the workflow calls again from where it stopped, and the record goes
        // through. A second worker, because the first cached the function as it was before the repair.
        await repairInputs(broken)
        await replayer!.stop()
        const fixedQueue = createMockJobQueue()
        const resumed = await runReplay(
            { hogQueue: fixedQueue, hogflowQueue: fixedQueue },
            { from_offset: blocked.next_offset, end_offset: blocked.end_offset }
        )
        expect(fixedQueue.queueInvocations).toHaveBeenCalledWith([expect.objectContaining({ functionId: broken.id })])
        expect(resumed).toMatchObject({ next_offset: 1, blocked: null })
    })

    it('parks a workflow that cannot build, then replays it onto the workflow queue', async () => {
        // Every other case here is a destination. A workflow is the other source kind, and its
        // invocations go to a different queue, so nothing else covers that wiring.
        const flow = await insertHogFlow(
            hub.postgres,
            new FixtureHogFlowBuilder()
                .withTeamId(team.id)
                .withSimpleWorkflow({
                    trigger: { type: 'event', filters: HOG_FILTERS_EXAMPLES.broken_filters.filters as any },
                })
                .build()
        )

        const sourceQueue = createMockJobQueue()
        await startEventsConsumer({ hogQueue: sourceQueue, hogflowQueue: sourceQueue })
        const records = await parkEvent()
        expect(records).toHaveLength(1)
        const headers = Object.assign({}, ...(records[0].headers ?? []).map((h: any) => h))
        expect(headers.dlq_hog_flow_ids.toString()).toBe(flow.id)
        expect(headers.dlq_kinds.toString()).toBe('hog_flow')

        await hub.postgres.query(
            PostgresUse.COMMON_WRITE,
            `UPDATE posthog_hogflow SET trigger = $1 WHERE id = $2`,
            [JSON.stringify({ type: 'event', filters: HOG_FILTERS_EXAMPLES.no_filters.filters }), flow.id],
            'repair-hog-flow-trigger'
        )

        // Separate queues, so the assertion is about which one the workflow landed on.
        const hogQueue = createMockJobQueue()
        const hogflowQueue = createMockJobQueue()
        replayer = new CdpDlqReplayer(hub, createCdpConsumerDeps(hub, kafkaProducer), {
            hogQueue,
            hogflowQueue,
        })
        await replayer.replayBatch(records)

        expect(hogflowQueue.queueInvocations).toHaveBeenCalledWith([expect.objectContaining({ functionId: flow.id })])
        expect(hogQueue.queueInvocations).toHaveBeenCalledWith([])
    })

    it('parks bytes it cannot read, stops at them, and skips them only when told to', async () => {
        // The one step whose records are unreadable by construction: that is why they were parked.
        await insertHogFunction(hub.postgres, team.id, {
            ...HOG_EXAMPLES.simple_fetch,
            ...HOG_INPUTS_EXAMPLES.simple_fetch,
            ...HOG_FILTERS_EXAMPLES.no_filters,
            type: 'destination',
        })

        const sourceQueue = createMockJobQueue()
        await startEventsConsumer({ hogQueue: sourceQueue, hogflowQueue: sourceQueue })
        await kafkaProducer.produce({
            topic: eventsTopic,
            value: Buffer.from('not an event at all'),
            key: null,
        })
        await kafkaProducer.flush()

        const records = await readDlqRecords()
        const headers = Object.assign({}, ...(records[0].headers ?? []).map((h: any) => h))
        expect(headers.dlq_step.toString()).toBe('parse')
        // Nothing was built, so a replay is not restricted to either pipeline.
        expect(headers.dlq_kinds.toString()).toBe('')

        const replayQueue = createMockJobQueue()
        const blocked = await runReplay({ hogQueue: replayQueue, hogflowQueue: replayQueue })
        expect(blocked.blocked).toMatchObject({ offset: 0 })
        expect(replayQueue.queueInvocations).not.toHaveBeenCalled()

        await replayer!.stop()
        const skipped = await runReplay(
            { hogQueue: replayQueue, hogflowQueue: replayQueue },
            { skip_unreplayable: true }
        )
        expect(skipped).toMatchObject({ next_offset: 1, records_skipped: 1, skipped: [{ offset: 0 }], blocked: null })
        expect(replayQueue.queueInvocations).not.toHaveBeenCalled()
    })

    it.each([
        ['a window that ends before the record was parked', { end_timestamp_ms: 1 }, undefined],
        ['another team', { team_id: 999_999 }, undefined],
        ['other sources', { source_ids: ['00000000-0000-0000-0000-000000000000'] }, undefined],
        ['a position past the record', { from_offset: 1 }, undefined],
        ['a retry whose last heartbeat is past the record', {}, 'past'],
    ] as const)('replays nothing for %s', async (_case, input, heartbeat) => {
        // Each run reads only what it was asked for. Reading wider re-delivers what an earlier run,
        // or an earlier attempt of this one, already queued.
        const fn = await insertHogFunction(hub.postgres, team.id, {
            ...HOG_EXAMPLES.simple_fetch,
            ...HOG_FILTERS_EXAMPLES.no_filters,
            type: 'destination',
            inputs_schema: [{ key: 'url', type: 'string', label: 'Webhook URL', required: true }],
            inputs: BROKEN_INPUTS,
        })

        const sourceQueue = createMockJobQueue()
        await startEventsConsumer({ hogQueue: sourceQueue, hogflowQueue: sourceQueue })
        await parkEvent()
        await repairInputs(fn)

        const replayQueue = createMockJobQueue()
        const result = await runReplay(
            { hogQueue: replayQueue, hogflowQueue: replayQueue },
            input,
            heartbeat
                ? {
                      partition: 0,
                      next_offset: 1,
                      end_offset: 1,
                      records_read: 1,
                      records_in_scope: 1,
                      records_out_of_scope: 0,
                      records_unreadable: 0,
                      records_skipped: 0,
                      invocations_queued: 1,
                      skipped: [],
                      blocked: null,
                  }
                : undefined
        )

        const queued = replayQueue.queueInvocations.mock.calls.flatMap(([invocations]: [any[]]) => invocations)
        expect(queued).toEqual([])
        expect(result.blocked).toBeNull()
    })

    it('reports what a dry run would replay without queueing anything', async () => {
        // A rebuild reports billing, takes rate limit tokens and writes masking state, so a dry run
        // that rebuilt anything would change what the real run then does.
        await insertHogFunction(hub.postgres, team.id, {
            ...HOG_EXAMPLES.simple_fetch,
            ...HOG_FILTERS_EXAMPLES.no_filters,
            type: 'destination',
            inputs_schema: [{ key: 'url', type: 'string', label: 'Webhook URL', required: true }],
            inputs: BROKEN_INPUTS,
        })

        const sourceQueue = createMockJobQueue()
        await startEventsConsumer({ hogQueue: sourceQueue, hogflowQueue: sourceQueue })
        await parkEvent()

        const replayQueue = createMockJobQueue()
        const result = await runReplay({ hogQueue: replayQueue, hogflowQueue: replayQueue }, { dry_run: true })

        expect(result).toMatchObject({ records_read: 1, records_in_scope: 1, invocations_queued: 0, blocked: null })
        expect(replayQueue.queueInvocations).not.toHaveBeenCalled()
    })
})
