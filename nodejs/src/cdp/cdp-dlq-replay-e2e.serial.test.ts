import { createMockJobQueue } from '~/tests/helpers/mocks/job-queue.mock'
import { MockKafkaProducerWrapper } from '~/tests/helpers/mocks/producer.mock'
import '~/tests/helpers/mocks/request.mock'

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
import { CdpDlqReplayConsumer } from './consumers/cdp-dlq-replay.consumer'
import { CdpEventsConsumer } from './consumers/cdp-events.consumer'
import { HogFunctionType } from './types'

const ActualKafkaProducerWrapper = jest.requireActual('~/common/kafka/producer').KafkaProducerWrapper

// Truncated bytecode: resolving this input throws, the way a narrowed builtin arity did.
const BROKEN_INPUTS = { url: { order: 0, value: 'https://example.com', bytecode: ['_H', 1, 2] } }

describe('CDP dead-letter replay', () => {
    jest.setTimeout(60000)

    let hub: Hub
    let team: Team
    let kafkaProducer: KafkaProducerWrapper
    let eventsConsumer: CdpEventsConsumer | undefined
    let replayConsumer: CdpDlqReplayConsumer | undefined
    let dlqTopic: string

    beforeEach(async () => {
        MockKafkaProducerWrapper.create = jest.fn((...args) => ActualKafkaProducerWrapper.create(...args))

        // The dead-letter topic is per test. It is not deleted between runs, so a shared one would
        // hand each run the records every earlier run parked and there would be nothing to assert.
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
        await Promise.all([eventsConsumer?.stop(), replayConsumer?.stop()])
        eventsConsumer = undefined
        replayConsumer = undefined
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

    it('parks an event that cannot build, then rebuilds only that function after the fix', async () => {
        const broken = await insertHogFunction(hub.postgres, team.id, {
            ...HOG_EXAMPLES.simple_fetch,
            ...HOG_FILTERS_EXAMPLES.no_filters,
            type: 'destination',
            inputs_schema: [{ key: 'url', type: 'string', label: 'Webhook URL', required: true }],
            inputs: BROKEN_INPUTS as any,
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
        hub.CDP_DLQ_REPLAY_DRY_RUN = false

        const replayQueue = createMockJobQueue()
        replayConsumer = new CdpDlqReplayConsumer(hub, createCdpConsumerDeps(hub, kafkaProducer), {
            hogQueue: replayQueue,
            hogflowQueue: replayQueue,
        })
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

    it('counts what it would deliver without queueing anything in a dry run', async () => {
        const broken = await insertHogFunction(hub.postgres, team.id, {
            ...HOG_EXAMPLES.simple_fetch,
            ...HOG_FILTERS_EXAMPLES.no_filters,
            type: 'destination',
            inputs_schema: [{ key: 'url', type: 'string', label: 'Webhook URL', required: true }],
            inputs: BROKEN_INPUTS as any,
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

        await repairInputs(broken)

        hub.CDP_DLQ_REPLAY_TOPIC = dlqTopic
        hub.CDP_DLQ_REPLAY_RUN_ID = `e2e-dry-${event.uuid}`
        hub.CDP_DLQ_REPLAY_DRY_RUN = true

        const replayQueue = createMockJobQueue()
        replayConsumer = new CdpDlqReplayConsumer(hub, createCdpConsumerDeps(hub, kafkaProducer), {
            hogQueue: replayQueue,
            hogflowQueue: replayQueue,
        })
        await replayConsumer.start()

        await waitForExpect(() => {
            expect(replayConsumer!.counts.replayed).toBe(1)
        }, 30000)

        expect(replayConsumer.counts.queued).toBe(0)
        expect(replayQueue.queueInvocations).not.toHaveBeenCalled()
        expect(replayConsumer.counts.byTarget).toEqual({ [`${team.id}|${broken.id}|inputs`]: 1 })
    })
})
