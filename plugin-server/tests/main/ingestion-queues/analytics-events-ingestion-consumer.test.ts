import { v4 } from 'uuid'

import { KAFKA_EVENTS_PLUGIN_INGESTION, KAFKA_EVENTS_PLUGIN_INGESTION_OVERFLOW } from '../../../src/config/kafka-topics'
import {
    eachBatchParallelIngestion,
    IngestionOverflowMode,
} from '../../../src/main/ingestion-queues/batch-processing/each-batch-ingestion'
import { IngestionConsumer } from '../../../src/main/ingestion-queues/kafka-queue'
import { Hub } from '../../../src/types'
import { createHub } from '../../../src/utils/db/hub'
import { ConfiguredLimiter } from '../../../src/utils/token-bucket'
import { createOrganization, createTeam } from '../../helpers/sql'
import { captureIngestionWarning } from './../../../src/worker/ingestion/utils'

// jest.mock('../../../src/utils/status')
jest.mock('./../../../src/worker/ingestion/utils')

const captureEndpointEvent = {
    uuid: 'uuid1',
    distinct_id: 'id',
    ip: null,
    site_url: '',
    data: JSON.stringify({
        event: 'event',
        properties: {},
    }),
    team_id: 1,
    now: null,
    sent_at: null,
}

describe('eachBatchParallelIngestion with overflow reroute', () => {
    let queue: Pick<IngestionConsumer, 'pluginsServer' | 'workerMethods'>
    let hub: Hub
    let closeHub: () => Promise<void>

    function createBatchWithMultipleEventsWithKeys(events: any[], timestamp?: any): any {
        return events.map((event) => ({
            partition: 0,
            topic: KAFKA_EVENTS_PLUGIN_INGESTION,
            value: JSON.stringify(event),
            timestamp,
            offset: event.offset,
            key: event.team_id + ':' + event.distinct_id,
        }))
    }

    beforeAll(async () => {
        ;[hub, closeHub] = await createHub()
    })

    afterAll(async () => {
        await closeHub()
    })

    beforeEach(() => {
        queue = {
            pluginsServer: hub,
            workerMethods: {
                runAsyncHandlersEventPipeline: jest.fn(),
                runEventPipeline: jest.fn(),
            },
        }
    })

    it('reroutes events with no key to OVERFLOW topic', async () => {
        const batch = [
            {
                partition: 0,
                topic: KAFKA_EVENTS_PLUGIN_INGESTION,
                value: JSON.stringify(captureEndpointEvent),
                timestamp: captureEndpointEvent['timestamp'],
                offset: captureEndpointEvent['offset'],
                key: null,
            },
        ]

        const consume = jest.spyOn(ConfiguredLimiter, 'consume').mockImplementation(() => false)

        await eachBatchParallelIngestion(batch, queue, IngestionOverflowMode.Reroute)

        expect(consume).not.toHaveBeenCalled()
        expect(captureIngestionWarning).not.toHaveBeenCalled()
        expect(queue.pluginsServer.kafkaProducer.produce).toHaveBeenCalledWith({
            topic: KAFKA_EVENTS_PLUGIN_INGESTION_OVERFLOW,
            value: JSON.stringify(captureEndpointEvent),
            timestamp: captureEndpointEvent['timestamp'],
            offset: captureEndpointEvent['offset'],
            key: null,
            waitForAck: true,
        })

        // Event is not processed here
        expect(queue.workerMethods.runEventPipeline).not.toHaveBeenCalled()
    })

    it('reroutes excess events to OVERFLOW topic', async () => {
        const batch = createBatchWithMultipleEventsWithKeys([captureEndpointEvent])
        const consume = jest.spyOn(ConfiguredLimiter, 'consume').mockImplementation(() => false)

        await eachBatchParallelIngestion(batch, queue, IngestionOverflowMode.Reroute)

        expect(consume).toHaveBeenCalledWith(
            captureEndpointEvent['team_id'] + ':' + captureEndpointEvent['distinct_id'],
            1
        )
        expect(captureIngestionWarning).not.toHaveBeenCalled()
        expect(queue.pluginsServer.kafkaProducer.produce).toHaveBeenCalledWith({
            topic: KAFKA_EVENTS_PLUGIN_INGESTION_OVERFLOW,
            value: JSON.stringify(captureEndpointEvent),
            timestamp: captureEndpointEvent['timestamp'],
            offset: captureEndpointEvent['offset'],
            key: null,
            waitForAck: true,
        })

        // Event is not processed here
        expect(queue.workerMethods.runEventPipeline).not.toHaveBeenCalled()
    })

    it('does not reroute if not over capacity limit', async () => {
        const batch = createBatchWithMultipleEventsWithKeys([captureEndpointEvent])
        const consume = jest.spyOn(ConfiguredLimiter, 'consume').mockImplementation(() => true)

        await eachBatchParallelIngestion(batch, queue, IngestionOverflowMode.Reroute)

        expect(consume).toHaveBeenCalledWith(
            captureEndpointEvent['team_id'] + ':' + captureEndpointEvent['distinct_id'],
            1
        )
        expect(captureIngestionWarning).not.toHaveBeenCalled()
        expect(queue.pluginsServer.kafkaProducer.produce).not.toHaveBeenCalled()
        // Event is processed
        expect(queue.workerMethods.runEventPipeline).toHaveBeenCalled()
    })

    it('throws error if Kafka is down in reroute mode', async () => {
        const batch = createBatchWithMultipleEventsWithKeys([captureEndpointEvent])
        const consume = jest.spyOn(ConfiguredLimiter, 'consume').mockImplementation(() => false)
        queue.pluginsServer.kafkaProducer.produce = jest.fn(() => {
            throw new Error('Kafka is down')
        })

        await expect(eachBatchParallelIngestion(batch, queue, IngestionOverflowMode.Reroute)).rejects.toThrow(
            'Kafka is down'
        )

        expect(consume).toHaveBeenCalledWith(
            captureEndpointEvent['team_id'] + ':' + captureEndpointEvent['distinct_id'],
            1
        )
        expect(captureIngestionWarning).not.toHaveBeenCalled()
        expect(queue.pluginsServer.kafkaProducer.produce).toHaveBeenCalled()
        // Event is not processed here
        expect(queue.workerMethods.runEventPipeline).not.toHaveBeenCalled()
    })

    it('throws error if Kafka is down in consume mode', async () => {
        const organizationId = await createOrganization(queue.pluginsServer.postgres)
        const token = v4()
        await createTeam(queue.pluginsServer.postgres, organizationId, token)

        const event = {
            distinct_id: 'id',
            ip: null,
            site_url: '',
            data: JSON.stringify({
                event: 'event',
                properties: {},
            }),
            token: token,
            now: null,
            sent_at: null,
        }

        const message = {
            partition: 0,
            topic: KAFKA_EVENTS_PLUGIN_INGESTION,
            value: Buffer.from(JSON.stringify(event)),
            timestamp: event['timestamp'],
            offset: 0,
            size: 0,
        }

        queue.pluginsServer.kafkaProducer.produce = jest.fn(() => {
            throw new Error('Kafka is down')
        })

        await expect(
            eachBatchParallelIngestion([message], queue as any, IngestionOverflowMode.Consume)
        ).rejects.toThrow('Kafka is down')

        expect(captureIngestionWarning).not.toHaveBeenCalled()
        expect(queue.pluginsServer.kafkaProducer.produce).toHaveBeenCalled()
        // Event is not processed here
        expect(queue.workerMethods.runEventPipeline).not.toHaveBeenCalled()
    })

    it('throws error if postgres is down in consume mode', async () => {
        // This very roughly simulates transient postgres errors, but the
        // handling of such errors may be different down the stack so this isn't
        // exhaustive.
        const organizationId = await createOrganization(queue.pluginsServer.postgres)
        const token = v4()
        await createTeam(queue.pluginsServer.postgres, organizationId, token)

        const event = {
            distinct_id: 'id',
            ip: null,
            site_url: '',
            data: JSON.stringify({
                event: 'event',
                properties: {},
            }),
            token: token,
            now: null,
            sent_at: null,
        }

        const message = {
            partition: 0,
            topic: KAFKA_EVENTS_PLUGIN_INGESTION,
            value: Buffer.from(JSON.stringify(event)),
            timestamp: event['timestamp'],
            offset: 0,
            size: 0,
        }

        queue.pluginsServer.postgres.query = jest.fn(() => {
            throw new Error('Postgres is down')
        })

        await expect(
            eachBatchParallelIngestion([message], queue as any, IngestionOverflowMode.Consume)
        ).rejects.toThrow('Postgres is down')
    })
})
