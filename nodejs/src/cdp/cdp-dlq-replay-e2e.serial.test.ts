import { createMockJobQueue } from '~/tests/helpers/mocks/job-queue.mock'
import { MockKafkaProducerWrapper } from '~/tests/helpers/mocks/producer.mock'
import { mockFetch } from '~/tests/helpers/mocks/request.mock'

import { KAFKA_CDP_EVENTS_DLQ } from '~/common/config/kafka-topics'
import { KafkaProducerWrapper } from '~/common/kafka/producer'
import { closeHub, createHub } from '~/common/utils/db/hub'
import { PostgresUse } from '~/common/utils/db/postgres'
import { createCdpConsumerDeps } from '~/tests/helpers/cdp'
import { waitForExpect } from '~/tests/helpers/expectations'
import { TEST_KAFKA_TOPICS, createKafkaTestTopicName, ensureKafkaTopics } from '~/tests/helpers/kafka'
import { getFirstTeam, resetTestDatabase } from '~/tests/helpers/sql'

import { Hub, Team } from '../types'
import { HOG_EXAMPLES, HOG_FILTERS_EXAMPLES, HOG_INPUTS_EXAMPLES } from './_tests/examples'
import { createIncomingEvent, createKafkaMessage, insertHogFunction } from './_tests/fixtures'
import { CdpCyclotronWorker } from './consumers/cdp-cyclotron-worker.consumer'
import { CdpDlqReplayConsumer, UNSET_RUN_ID } from './consumers/cdp-dlq-replay.consumer'
import { CdpEventsConsumer } from './consumers/cdp-events.consumer'
import { CyclotronJobQueueKafka } from './services/job-queue/job-queue-kafka'
import { CyclotronJobQueuePostgresV2 } from './services/job-queue/job-queue-postgres-v2'
import { HogFunctionType } from './types'

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
    let replayConsumer: CdpDlqReplayConsumer | undefined
    let cyclotronWorker: CdpCyclotronWorker | undefined
    let dlqTopic: string
    let onComplete: jest.Mock

    beforeEach(async () => {
        MockKafkaProducerWrapper.create = jest.fn((...args) => ActualKafkaProducerWrapper.create(...args))

        // The dead-letter topic is per test. It is not deleted between runs, so a shared one would
        // hand each run the records every earlier run parked and there would be nothing to assert.
        onComplete = jest.fn()
        dlqTopic = createKafkaTestTopicName(KAFKA_CDP_EVENTS_DLQ)
        await ensureKafkaTopics([...TEST_KAFKA_TOPICS, dlqTopic])
        await resetTestDatabase()

        hub = await createHub()
        hub.CDP_DLQ_ENABLED = true
        hub.CDP_EVENTS_DLQ_TOPIC = dlqTopic
        kafkaProducer = await ActualKafkaProducerWrapper.create(hub.KAFKA_CLIENT_RACK)
        team = await getFirstTeam(hub.postgres)
    })

    afterEach(async () => {
        await Promise.all([eventsConsumer?.stop(), replayConsumer?.stop(), cyclotronWorker?.stop()])
        eventsConsumer = undefined
        replayConsumer = undefined
        cyclotronWorker = undefined
        await kafkaProducer.disconnect()
        await closeHub(hub)
    })

    /** Stands in for the forward fix: the same function, with inputs that now resolve. */
    const repairInputs = async (fn: HogFunctionType): Promise<void> => {
        await hub.postgres.query(
            PostgresUse.COMMON_WRITE,
            `UPDATE posthog_hogfunction SET inputs = $1 WHERE id = $2`,
            [JSON.stringify(HOG_INPUTS_EXAMPLES.simple_fetch.inputs), fn.id],
            'repair-hog-function-inputs'
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
        eventsConsumer = new CdpEventsConsumer(hub, createCdpConsumerDeps(hub, kafkaProducer), {
            hogQueue: sourceQueue,
            hogflowQueue: sourceQueue,
        })
        await eventsConsumer.start()

        const event = createIncomingEvent(team.id, {})
        const message = createKafkaMessage(event)
        const globals = await eventsConsumer._parseKafkaBatch([message])
        await eventsConsumer.processBatch(globals)
        await eventsConsumer['deadLetterService'].produceForBatch([message])
        await kafkaProducer.flush()

        // The healthy function delivered on the first pass. That is what the replay must not repeat.
        expect(sourceQueue.queueInvocations).toHaveBeenCalledWith([expect.objectContaining({ functionId: healthy.id })])

        // --- fix, then replay -------------------------------------------------------------
        await repairInputs(broken)

        hub.CDP_DLQ_REPLAY_TOPIC = dlqTopic
        hub.CDP_DLQ_REPLAY_RUN_ID = `e2e-${event.uuid}`

        const replayQueue = createMockJobQueue()
        replayConsumer = new CdpDlqReplayConsumer(
            hub,
            createCdpConsumerDeps(hub, kafkaProducer),
            { hogQueue: replayQueue, hogflowQueue: replayQueue },
            undefined,
            // A finished run kills the process in production. In a test that would take jest with it.
            onComplete
        )
        await replayConsumer.start()

        await waitForExpect(() => {
            expect(replayQueue.queueInvocations).toHaveBeenCalledWith([
                expect.objectContaining({ functionId: broken.id }),
            ])
        }, 30000)

        // Only the parked function was rebuilt: every invocation the replay queued is that one.
        const replayed = replayQueue.queueInvocations.mock.calls.flatMap(([invocations]: [any[]]) => invocations)
        expect(replayed.map((invocation: any) => invocation.functionId)).toEqual([broken.id])
        expect(replayed[0].queueMetadata).toMatchObject({ replayed_from_dlq: true })
        expect(replayConsumer.counts.replayed).toBe(1)
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
        eventsConsumer = new CdpEventsConsumer(hub, createCdpConsumerDeps(hub, kafkaProducer), {
            hogQueue: sourceQueue,
            hogflowQueue: sourceQueue,
        })
        await eventsConsumer.start()

        const event = createIncomingEvent(team.id, {})
        const message = createKafkaMessage(event)
        await eventsConsumer.processBatch(await eventsConsumer._parseKafkaBatch([message]))
        await eventsConsumer['deadLetterService'].produceForBatch([message])
        await kafkaProducer.flush()

        await repairInputs(brokenInputs)
        await repairFilters(brokenFilter)

        hub.CDP_DLQ_REPLAY_TOPIC = dlqTopic
        hub.CDP_DLQ_REPLAY_RUN_ID = `e2e-both-${event.uuid}`

        const replayQueue = createMockJobQueue()
        replayConsumer = new CdpDlqReplayConsumer(
            hub,
            createCdpConsumerDeps(hub, kafkaProducer),
            { hogQueue: replayQueue, hogflowQueue: replayQueue },
            undefined,
            // A finished run kills the process in production. In a test that would take jest with it.
            onComplete
        )
        await replayConsumer.start()

        await waitForExpect(() => {
            expect(replayConsumer!.counts.queued).toBe(2)
        }, 30000)

        // A finished run has to end the process. Stopping only the consumer leaves the server up
        // with a dead Kafka client, so the health check goes red, Kubernetes restarts the pod, and
        // the new process re-reads the end offsets and replays past the boundary it was given.
        await waitForExpect(() => {
            expect(onComplete).toHaveBeenCalled()
        }, 30000)

        // Both parked functions come back, each exactly once. Keying the targets by event UUID
        // without merging would drop one and queue the other twice.
        const replayed = replayQueue.queueInvocations.mock.calls.flatMap(([invocations]: [any[]]) => invocations)
        expect(replayed.map((invocation: any) => invocation.functionId).sort()).toEqual(
            [brokenFilter.id, brokenInputs.id].sort()
        )
    })

    it('sends the delivery for real: parked, fixed, replayed, and the destination is called', async () => {
        // Everything else here stops once an invocation is queued. This one runs the invocation
        // through cyclotron as well, so the whole loop is covered: the event fails to build, the
        // bytes land on a real topic, a real consumer group reads them back, the invocation is
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

        eventsConsumer = new CdpEventsConsumer(hub, createCdpConsumerDeps(hub, kafkaProducer), {
            hogQueue: kafkaQueue,
            hogflowQueue: postgresQueue,
        })
        await eventsConsumer.start()

        const event = createIncomingEvent(team.id, {})
        const message = createKafkaMessage(event)
        await eventsConsumer.processBatch(await eventsConsumer._parseKafkaBatch([message]))
        await eventsConsumer['deadLetterService'].produceForBatch([message])
        await kafkaProducer.flush()

        // Nothing was delivered: the only destination on this event could not be built.
        expect(mockFetch).not.toHaveBeenCalled()

        // The forward fix, then the replay, with cyclotron running to execute what it queues.
        await repairInputs(broken)
        cyclotronWorker = new CdpCyclotronWorker(hub, createCdpConsumerDeps(hub, kafkaProducer), kafkaQueue)
        await cyclotronWorker.start()

        hub.CDP_DLQ_REPLAY_TOPIC = dlqTopic
        hub.CDP_DLQ_REPLAY_RUN_ID = `e2e-full-${event.uuid}`

        replayConsumer = new CdpDlqReplayConsumer(
            hub,
            createCdpConsumerDeps(hub, kafkaProducer),
            { hogQueue: kafkaQueue, hogflowQueue: postgresQueue },
            undefined,
            onComplete
        )
        await replayConsumer.start()

        await waitForExpect(() => {
            expect(mockFetch).toHaveBeenCalledTimes(1)
        }, 30000)

        expect(mockFetch.mock.calls[0][0]).toBe('https://example.com/posthog-webhook')
    }, 60000)

    it('refuses to start until the run is named', async () => {
        // A replica scaled up before its policy is written must stop, not replay everything the
        // default open policy matches.
        hub.CDP_DLQ_REPLAY_TOPIC = dlqTopic
        hub.CDP_DLQ_REPLAY_RUN_ID = UNSET_RUN_ID

        const replayQueue = createMockJobQueue()
        const unnamed = new CdpDlqReplayConsumer(
            hub,
            createCdpConsumerDeps(hub, kafkaProducer),
            { hogQueue: replayQueue, hogflowQueue: replayQueue },
            undefined,
            onComplete
        )

        await expect(unnamed.start()).rejects.toThrow('CDP_DLQ_REPLAY_RUN_ID must be set')
        expect(replayQueue.queueInvocations).not.toHaveBeenCalled()
    })
})
