import { Settings } from 'luxon'

import { buildStringMatcher } from '../../../src/config/config'
import {
    eachBatchParallelIngestion,
    IngestionOverflowMode,
} from '../../../src/main/ingestion-queues/batch-processing/each-batch-ingestion'
import { TimestampFormat } from '../../../src/types'
import { IngestionWarningLimiter } from '../../../src/utils/token-bucket'
import { castTimestampOrNow } from '../../../src/utils/utils'

jest.mock('../../../src/utils/status')

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
    let mockQueueMessage: jest.Mock

    function createBatchWithMultipleEventsWithKeys(events: any[], timestamp?: any): any {
        return events.map((event) => ({
            value: JSON.stringify(event),
            timestamp,
            offset: event.offset,
            key: event.team_id + ':' + event.distinct_id,
        }))
    }

    beforeEach(() => {
        // luxon datetime lets you specify a fixed "now"
        Settings.now = () => new Date(2018, 4, 25).valueOf()

        mockQueueMessage = jest.fn()
        queue = {
            bufferSleep: jest.fn(),
            pluginsServer: {
                INGESTION_CONCURRENCY: 4,
                kafkaProducer: {
                    queueMessage: mockQueueMessage,
                },
                teamManager: {
                    getTeamForEvent: jest.fn(),
                },
                db: {
                    kafkaProducer: {
                        queueMessage: mockQueueMessage,
                    },
                },
            },
        }
    })

    it.each([IngestionOverflowMode.ConsumeSplitByDistinctId, IngestionOverflowMode.ConsumeSplitEvenly])(
        'raises ingestion warning when consuming from overflow %s',
        async (mode) => {
            const batch = createBatchWithMultipleEventsWithKeys([captureEndpointEvent1])
            const consume = jest.spyOn(IngestionWarningLimiter, 'consume').mockImplementation(() => true)

            queue.pluginsServer.teamManager.getTeamForEvent.mockResolvedValueOnce({ id: 1 })
            const tokenBlockList = buildStringMatcher('another_token,more_token', false)
            await eachBatchParallelIngestion(tokenBlockList, batch, queue, mode)

            expect(queue.pluginsServer.teamManager.getTeamForEvent).toHaveBeenCalledTimes(1)
            expect(consume).toHaveBeenCalledWith('1:ingestion_capacity_overflow:id', 1)
            expect(mockQueueMessage).toHaveBeenCalledWith({
                kafkaMessage: {
                    topic: 'clickhouse_ingestion_warnings_test',
                    messages: [
                        {
                            value: JSON.stringify({
                                team_id: 1,
                                type: 'ingestion_capacity_overflow',
                                source: 'plugin-server',
                                details: JSON.stringify({
                                    overflowDistinctId: 'id',
                                }),
                                timestamp: castTimestampOrNow(null, TimestampFormat.ClickHouse),
                            }),
                        },
                    ],
                },
                waitForAck: false,
            })

            // Event is processed
            expect(runEventPipeline).toHaveBeenCalled()
        }
    )

    it.each([IngestionOverflowMode.ConsumeSplitByDistinctId, IngestionOverflowMode.ConsumeSplitEvenly])(
        'does not raise ingestion warning when under threshold %s',
        async (mode) => {
            const batch = createBatchWithMultipleEventsWithKeys([captureEndpointEvent1])
            const consume = jest.spyOn(IngestionWarningLimiter, 'consume').mockImplementation(() => false)

            queue.pluginsServer.teamManager.getTeamForEvent.mockResolvedValueOnce({ id: 1 })
            const tokenBlockList = buildStringMatcher('another_token,more_token', false)
            await eachBatchParallelIngestion(tokenBlockList, batch, queue, mode)

            expect(consume).toHaveBeenCalledWith('1:ingestion_capacity_overflow:id', 1)
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
            const consume = jest.spyOn(IngestionWarningLimiter, 'consume').mockImplementation(() => false)

            queue.pluginsServer.teamManager.getTeamForEvent.mockResolvedValueOnce({ id: 1 })
            const tokenBlockList = buildStringMatcher('mytoken,more_token', false)
            await eachBatchParallelIngestion(tokenBlockList, batch, queue, mode)

            expect(queue.pluginsServer.kafkaProducer.queueMessage).not.toHaveBeenCalled()

            // captureEndpointEvent2 is processed, captureEndpointEvent1 are dropped
            expect(runEventPipeline).toHaveBeenCalledTimes(1)
            expect(consume).toHaveBeenCalledTimes(1)
        }
    )
})
