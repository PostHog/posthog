import { Message } from 'node-rdkafka'

import { buildStringMatcher } from '../../../src/config/config'
import { KAFKA_EVENTS_PLUGIN_INGESTION, KAFKA_EVENTS_PLUGIN_INGESTION_OVERFLOW } from '../../../src/config/kafka-topics'
import {
    computeKey,
    eachBatchParallelIngestion,
    IngestionOverflowMode,
} from '../../../src/main/ingestion-queues/batch-processing/each-batch-ingestion'
import { Hub } from '../../../src/types'
import { createHub } from '../../../src/utils/db/hub'
import { ConfiguredLimiter } from '../../../src/utils/token-bucket'
import { captureIngestionWarning } from './../../../src/worker/ingestion/utils'

jest.mock('../../../src/utils/status')
jest.mock('./../../../src/worker/ingestion/utils')

const runEventPipeline = jest.fn().mockResolvedValue('default value')

jest.mock('./../../../src/worker/ingestion/event-pipeline/runner', () => ({
    EventPipelineRunner: jest.fn().mockImplementation(() => ({
        runEventPipeline: runEventPipeline,
    })),
}))

const captureEndpointEvent1 = {
    uuid: 'uuid1',
    distinct_id: 'id',
    ip: null,
    site_url: '',
    data: JSON.stringify({
        event: 'event',
        properties: {},
    }),
    token: 'mytoken',
    now: null,
    sent_at: null,
}

const captureEndpointEvent2 = {
    uuid: 'uuid2',
    distinct_id: 'id',
    ip: null,
    site_url: '',
    data: JSON.stringify({
        event: 'event',
        properties: {},
    }),
    token: 'othertoken',
    now: null,
    sent_at: null,
}

describe('eachBatchParallelIngestion with overflow reroute', () => {
    let hub: Hub
    let closeServer: () => Promise<void>
    let queue: any

    function createBatchWithMultipleEvents(events: any[], timestamp?: any, withKey = true): Message[] {
        return events.map((event, i) => ({
            partition: 0,
            topic: KAFKA_EVENTS_PLUGIN_INGESTION,
            value: Buffer.from(JSON.stringify(event)),
            timestamp,
            offset: i,
            key: withKey ? computeKey(event) : null,
            size: 0, // irrelevant, but needed for type checking
        }))
    }

    beforeEach(async () => {
        ;[hub, closeServer] = await createHub()
        queue = {
            bufferSleep: jest.fn(),
            pluginsServer: hub,
        }
        jest.mock('./../../../src/worker/ingestion/event-pipeline/runner')
    })

    afterEach(async () => {
        await closeServer()
        jest.clearAllMocks()
    })

    it('reroutes events with no key to OVERFLOW topic', async () => {
        const now = Date.now()
        const [message] = createBatchWithMultipleEvents(
            [captureEndpointEvent1],
            now,
            false // act as if this message was intended to be routed to overflow by capture
        )

        const consume = jest.spyOn(ConfiguredLimiter, 'consume').mockImplementation(() => false)
        const produce = jest.spyOn(queue.pluginsServer.kafkaProducer, 'produce')

        const tokenBlockList = buildStringMatcher('another_token,more_token', false)
        await eachBatchParallelIngestion(tokenBlockList, [message], queue, IngestionOverflowMode.Reroute)

        expect(consume).not.toHaveBeenCalled()
        expect(captureIngestionWarning).not.toHaveBeenCalled()
        expect(produce).toHaveBeenCalledWith({
            topic: KAFKA_EVENTS_PLUGIN_INGESTION_OVERFLOW,
            value: message.value,
            key: null,
            waitForAck: true,
        })

        // Event is not processed here
        expect(runEventPipeline).not.toHaveBeenCalled()
    })

    it.each([IngestionOverflowMode.Reroute, IngestionOverflowMode.RerouteRandomly])(
        'reroutes excess events to OVERFLOW topic (mode=%p)',
        async (overflowMode) => {
            const now = Date.now()
            const event = captureEndpointEvent1
            const [message] = createBatchWithMultipleEvents([event], now)
            const consume = jest.spyOn(ConfiguredLimiter, 'consume').mockImplementation(() => false)
            const produce = jest.spyOn(queue.pluginsServer.kafkaProducer, 'produce')

            const tokenBlockList = buildStringMatcher('another_token,more_token', false)
            await eachBatchParallelIngestion(tokenBlockList, [message], queue, overflowMode)

            expect(consume).toHaveBeenCalledWith(message.key, 1, now)
            expect(captureIngestionWarning).not.toHaveBeenCalled()
            expect(produce).toHaveBeenCalledWith({
                topic: KAFKA_EVENTS_PLUGIN_INGESTION_OVERFLOW,
                value: message.value,
                key: overflowMode === IngestionOverflowMode.Reroute ? message.key : null,
                waitForAck: true,
            })
        }
    )

    it('does not reroute if not over capacity limit', async () => {
        const now = Date.now()
        const batch = createBatchWithMultipleEvents([captureEndpointEvent1, captureEndpointEvent2], now)
        const consume = jest.spyOn(ConfiguredLimiter, 'consume').mockImplementation(() => true)
        const produce = jest.spyOn(queue.pluginsServer.kafkaProducer, 'produce')

        const tokenBlockList = buildStringMatcher('another_token,more_token', false)
        await eachBatchParallelIngestion(tokenBlockList, batch, queue, IngestionOverflowMode.Reroute)

        expect(consume).toHaveBeenCalledWith(
            captureEndpointEvent1['token'] + ':' + captureEndpointEvent1['distinct_id'],
            1,
            now
        )
        expect(consume).toHaveBeenCalledWith(
            captureEndpointEvent2['token'] + ':' + captureEndpointEvent2['distinct_id'],
            1,
            now
        )
        expect(captureIngestionWarning).not.toHaveBeenCalled()
        expect(produce).not.toHaveBeenCalled()
        // Event is processed
        expect(runEventPipeline).toHaveBeenCalledTimes(2)
    })

    it('does drop events from blocked tokens', async () => {
        const now = Date.now()
        const batch = createBatchWithMultipleEvents(
            [captureEndpointEvent1, captureEndpointEvent2, captureEndpointEvent1],
            now
        )
        const produce = jest.spyOn(queue.pluginsServer.kafkaProducer, 'produce')
        const consume = jest.spyOn(ConfiguredLimiter, 'consume').mockImplementation(() => true)

        const tokenBlockList = buildStringMatcher('mytoken,another_token', false)
        await eachBatchParallelIngestion(tokenBlockList, batch, queue, IngestionOverflowMode.Reroute)

        // Event captureEndpointEvent1 is dropped , captureEndpointEvent2 goes though
        expect(consume).toHaveBeenCalledWith(
            captureEndpointEvent2['token'] + ':' + captureEndpointEvent2['distinct_id'],
            1,
            now
        )
        expect(captureIngestionWarning).not.toHaveBeenCalled()
        expect(produce).not.toHaveBeenCalled()
        expect(runEventPipeline).toHaveBeenCalledTimes(1)
    })
})
