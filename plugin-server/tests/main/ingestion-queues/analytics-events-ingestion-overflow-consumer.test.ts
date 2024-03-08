import { buildStringMatcher } from '../../../src/config/config'
import {
    eachBatchParallelIngestion,
    IngestionOverflowMode,
} from '../../../src/main/ingestion-queues/batch-processing/each-batch-ingestion'
import { OverflowWarningLimiter } from '../../../src/utils/token-bucket'
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

describe('eachBatchParallelIngestion with overflow consume', () => {
    let queue: any

    function createBatchWithMultipleEventsWithKeys(events: any[], timestamp?: any): any {
        return events.map((event) => ({
            value: JSON.stringify(event),
            timestamp,
            offset: event.offset,
            key: event.team_id + ':' + event.distinct_id,
        }))
    }

    beforeEach(() => {
        queue = {
            bufferSleep: jest.fn(),
            pluginsServer: {
                INGESTION_CONCURRENCY: 4,
                kafkaProducer: {
                    queueMessage: jest.fn(),
                },
                teamManager: {
                    getTeamForEvent: jest.fn(),
                },
                db: 'database',
            },
        }
    })

    it.each([IngestionOverflowMode.ConsumeSplitByDistinctId, IngestionOverflowMode.ConsumeSplitEvenly])(
        'raises ingestion warning when consuming from overflow %s',
        async (mode) => {
            const batch = createBatchWithMultipleEventsWithKeys([captureEndpointEvent1])
            const consume = jest.spyOn(OverflowWarningLimiter, 'consume').mockImplementation(() => true)

            queue.pluginsServer.teamManager.getTeamForEvent.mockResolvedValueOnce({ id: 1 })
            const tokenBlockList = buildStringMatcher('another_token,more_token', false)
            await eachBatchParallelIngestion(tokenBlockList, batch, queue, mode)

            expect(queue.pluginsServer.teamManager.getTeamForEvent).toHaveBeenCalledTimes(1)
            expect(consume).toHaveBeenCalledWith('1:id', 1)
            expect(captureIngestionWarning).toHaveBeenCalledWith(
                queue.pluginsServer.db,
                1,
                'ingestion_capacity_overflow',
                {
                    overflowDistinctId: captureEndpointEvent1['distinct_id'],
                }
            )

            // Event is processed
            expect(runEventPipeline).toHaveBeenCalled()
        }
    )

    it.each([IngestionOverflowMode.ConsumeSplitByDistinctId, IngestionOverflowMode.ConsumeSplitEvenly])(
        'does not raise ingestion warning when under threshold %s',
        async (mode) => {
            const batch = createBatchWithMultipleEventsWithKeys([captureEndpointEvent1])
            const consume = jest.spyOn(OverflowWarningLimiter, 'consume').mockImplementation(() => false)

            queue.pluginsServer.teamManager.getTeamForEvent.mockResolvedValueOnce({ id: 1 })
            const tokenBlockList = buildStringMatcher('another_token,more_token', false)
            await eachBatchParallelIngestion(tokenBlockList, batch, queue, mode)

            expect(consume).toHaveBeenCalledWith('1:id', 1)
            expect(captureIngestionWarning).not.toHaveBeenCalled()
            expect(queue.pluginsServer.kafkaProducer.queueMessage).not.toHaveBeenCalled()

            // Event is processed
            expect(runEventPipeline).toHaveBeenCalled()
        }
    )

    it.each([IngestionOverflowMode.ConsumeSplitByDistinctId, IngestionOverflowMode.ConsumeSplitEvenly])(
        'does drop events from blocked tokens %s',
        async (mode) => {
            const batch = createBatchWithMultipleEventsWithKeys([
                captureEndpointEvent1,
                captureEndpointEvent2,
                captureEndpointEvent1,
            ])
            const consume = jest.spyOn(OverflowWarningLimiter, 'consume').mockImplementation(() => false)

            queue.pluginsServer.teamManager.getTeamForEvent.mockResolvedValueOnce({ id: 1 })
            const tokenBlockList = buildStringMatcher('mytoken,more_token', false)
            await eachBatchParallelIngestion(tokenBlockList, batch, queue, mode)

            expect(captureIngestionWarning).not.toHaveBeenCalled()
            expect(queue.pluginsServer.kafkaProducer.queueMessage).not.toHaveBeenCalled()

            // captureEndpointEvent2 is processed, captureEndpointEvent1 are dropped
            expect(runEventPipeline).toHaveBeenCalledTimes(1)
            expect(consume).toHaveBeenCalledTimes(1)
        }
    )
})
