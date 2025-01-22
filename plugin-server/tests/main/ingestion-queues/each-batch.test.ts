import { buildStringMatcher } from '../../../src/config/config'
import { KAFKA_EVENTS_PLUGIN_INGESTION } from '../../../src/config/kafka-topics'
import {
    eachBatchParallelIngestion,
    IngestionOverflowMode,
    splitIngestionBatch,
} from '../../../src/main/ingestion-queues/batch-processing/each-batch-ingestion'
import { eachBatchAppsOnEventHandlers } from '../../../src/main/ingestion-queues/batch-processing/each-batch-onevent'
import * as batchProcessingMetrics from '../../../src/main/ingestion-queues/batch-processing/metrics'
import { ClickHouseTimestamp, ClickHouseTimestampSecondPrecision, RawKafkaEvent } from '../../../src/types'
import { runOnEvent } from '../../../src/worker/plugins/run'
import { pluginConfig39 } from '../../helpers/plugins'

jest.mock('../../../src/worker/plugins/run')

jest.mock('../../../src/utils/status')
jest.mock('./../../../src/worker/ingestion/utils')

const runEventPipeline = jest.fn().mockResolvedValue('default value')

jest.mock('./../../../src/worker/ingestion/event-pipeline/runner', () => ({
    EventPipelineRunner: jest.fn().mockImplementation(() => ({
        runEventPipeline: runEventPipeline,
    })),
}))

const kafkaEvent: RawKafkaEvent = {
    event: '$pageview',
    properties: JSON.stringify({
        $ip: '127.0.0.1',
    }),
    uuid: 'uuid1',
    elements_chain: '',
    timestamp: '2020-02-23 02:15:00.00' as ClickHouseTimestamp,
    team_id: 2,
    project_id: 1,
    distinct_id: 'my_id',
    created_at: '2020-02-23 02:15:00.00' as ClickHouseTimestamp,
    person_id: 'F99FA0A1-E0C2-4CFE-A09A-4C3C4327A4CC',
    person_created_at: '2020-02-20 02:15:00' as ClickHouseTimestampSecondPrecision, // Match createEvent ts format
    person_properties: '{}',
}

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

describe('eachBatchX', () => {
    let queue: any

    function createKafkaJSBatch(event: any, timestamp?: any): any {
        return createKafkaJSBatchWithMultipleEvents([event], timestamp)
    }

    function createKafkaJSBatchWithMultipleEvents(events: any[], timestamp?: any): any {
        return {
            batch: {
                partition: 0,
                messages: events.map((event) => ({
                    value: JSON.stringify(event),
                    // if event has timestamp use it, otherwise use timestamp
                    timestamp: event.kafkaTimestamp || timestamp,
                    offset: event.offset,
                })),
            },
            resolveOffset: jest.fn(),
            heartbeat: jest.fn(),
            commitOffsetsIfNecessary: jest.fn(),
            isRunning: jest.fn(() => true),
            isStale: jest.fn(() => false),
        }
    }
    function createBatchWithMultipleEvents(events: any[], timestamp?: any): any {
        return events.map((event, offset) => ({
            value: JSON.stringify(event),
            timestamp,
            offset: offset,
            partition: 0,
            topic: KAFKA_EVENTS_PLUGIN_INGESTION,
        }))
    }

    function createBatch(event: any, timestamp?: any): any {
        return createBatchWithMultipleEvents([event], timestamp)
    }

    beforeEach(() => {
        queue = {
            bufferSleep: jest.fn(),
            pluginsServer: {
                TASKS_PER_WORKER: 10,
                INGESTION_CONCURRENCY: 4,
                kafkaProducer: {
                    queueMessages: jest.fn(() => Promise.resolve()),
                },
                pluginConfigsPerTeam: new Map(),
            },
        }
    })

    describe('eachBatchAppsOnEventHandlers', () => {
        it('calls runOnEvent when useful', async () => {
            queue.pluginsServer.pluginConfigsPerTeam.set(2, [pluginConfig39])
            await eachBatchAppsOnEventHandlers(createKafkaJSBatch(kafkaEvent), queue)
            // TODO fix to jest spy on the actual function
            expect(runOnEvent).toHaveBeenCalledWith(
                expect.anything(),
                expect.objectContaining({
                    eventUuid: 'uuid1',
                    teamId: 2,
                    distinctId: 'my_id',
                })
            )
        })
        it('skip runOnEvent when no pluginconfig for team', async () => {
            queue.pluginsServer.pluginConfigsPerTeam.clear()
            await eachBatchAppsOnEventHandlers(createKafkaJSBatch(kafkaEvent), queue)
            expect(runOnEvent).not.toHaveBeenCalled()
        })
    })

    describe('eachBatchParallelIngestion', () => {
        it('calls runEventPipeline', async () => {
            const batch = createBatch(captureEndpointEvent)
            const tokenBlockList = buildStringMatcher('another_token,more_token', false)
            await eachBatchParallelIngestion(tokenBlockList, batch, queue, IngestionOverflowMode.Disabled)

            expect(runEventPipeline).toHaveBeenCalledWith({
                distinct_id: 'id',
                event: 'event',
                properties: {},
                ip: null,
                now: null,
                sent_at: null,
                site_url: '',
                team_id: 1,
                uuid: 'uuid1',
            })
        })

        it("doesn't fail the batch if runEventPipeline rejects once then succeeds on retry", async () => {
            const batch = createBatch(captureEndpointEvent)
            runEventPipeline.mockImplementationOnce(() => Promise.reject('runEventPipeline nopes out'))
            const tokenBlockList = buildStringMatcher('another_token,more_token', false)
            await eachBatchParallelIngestion(tokenBlockList, batch, queue, IngestionOverflowMode.Disabled)
            expect(runEventPipeline).toHaveBeenCalledTimes(2)
        })

        it('fails the batch if one deferred promise rejects', async () => {
            const batch = createBatch(captureEndpointEvent)
            runEventPipeline.mockImplementationOnce(() =>
                Promise.resolve({
                    ackPromises: [Promise.resolve(), Promise.reject('deferred nopes out')],
                })
            )
            const tokenBlockList = buildStringMatcher('another_token,more_token', false)
            await expect(
                eachBatchParallelIngestion(tokenBlockList, batch, queue, IngestionOverflowMode.Disabled)
            ).rejects.toBe('deferred nopes out')
            expect(runEventPipeline).toHaveBeenCalledTimes(1)
        })

        it.each([IngestionOverflowMode.ConsumeSplitByDistinctId, IngestionOverflowMode.Disabled])(
            'batches events by team or token and distinct_id %s',
            (mode) => {
                const batch = createBatchWithMultipleEvents([
                    { ...captureEndpointEvent, team_id: 3, distinct_id: 'a' },
                    { ...captureEndpointEvent, team_id: 3, distinct_id: 'a' },
                    { ...captureEndpointEvent, team_id: 3, distinct_id: 'b' },
                    { ...captureEndpointEvent, team_id: 4, distinct_id: 'a' },
                    { ...captureEndpointEvent, team_id: 4, distinct_id: 'a' },
                    { ...captureEndpointEvent, team_id: 4, distinct_id: 'b' },
                    { ...captureEndpointEvent, team_id: undefined, token: 'tok', distinct_id: 'a' },
                    { ...captureEndpointEvent, team_id: undefined, token: 'tok', distinct_id: 'a' },
                    { ...captureEndpointEvent, team_id: undefined, token: 'tok', distinct_id: 'b' },
                    { ...captureEndpointEvent, team_id: 3, distinct_id: 'c' },
                    { ...captureEndpointEvent, team_id: 3, distinct_id: 'b' },
                    { ...captureEndpointEvent, team_id: 3, distinct_id: 'a' },
                ])
                const stats = new Map()
                const tokenBlockList = buildStringMatcher('another_token,more_token', false)
                for (const group of splitIngestionBatch(tokenBlockList, batch, mode).toProcess) {
                    const key = `${group[0].pluginEvent.team_id}:${group[0].pluginEvent.token}:${group[0].pluginEvent.distinct_id}`
                    for (const { pluginEvent: event } of group) {
                        expect(`${event.team_id}:${event.token}:${event.distinct_id}`).toEqual(key)
                    }
                    stats.set(key, group.length)
                }
                expect(stats.size).toEqual(7)
                expect(stats).toEqual(
                    new Map([
                        ['3:undefined:a', 3],
                        ['3:undefined:b', 2],
                        ['3:undefined:c', 1],
                        ['4:undefined:a', 2],
                        ['4:undefined:b', 1],
                        ['undefined:tok:a', 2],
                        ['undefined:tok:b', 1],
                    ])
                )
            }
        )

        it('does not batch events when consuming overflow', () => {
            const input = createBatchWithMultipleEvents([
                { ...captureEndpointEvent, team_id: 3, distinct_id: 'a' },
                { ...captureEndpointEvent, team_id: 3, distinct_id: 'a' },
                { ...captureEndpointEvent, team_id: 3, distinct_id: 'b' },
                { ...captureEndpointEvent, team_id: 4, distinct_id: 'a' },
                { ...captureEndpointEvent, team_id: 4, distinct_id: 'a' },
            ])
            const tokenBlockList = buildStringMatcher('another_token,more_token', false)
            const batches = splitIngestionBatch(
                tokenBlockList,
                input,
                IngestionOverflowMode.ConsumeSplitEvenly
            ).toProcess
            expect(batches.length).toEqual(input.length)
            for (const group of batches) {
                expect(group.length).toEqual(1)
            }
        })

        it('batches events but commits offsets only once', async () => {
            const ingestEventBatchingInputLengthSummarySpy = jest.spyOn(
                batchProcessingMetrics.ingestEventBatchingInputLengthSummary,
                'observe'
            )
            const ingestEventBatchingBatchCountSummarySpy = jest.spyOn(
                batchProcessingMetrics.ingestEventBatchingBatchCountSummary,
                'observe'
            )
            const batch = createBatchWithMultipleEvents([
                { ...captureEndpointEvent, offset: 1, team_id: 3 },
                { ...captureEndpointEvent, offset: 2, team_id: 3 }, // repeat
                { ...captureEndpointEvent, offset: 3, team_id: 3 }, // repeat
                { ...captureEndpointEvent, offset: 4, team_id: 3 }, // repeat
                { ...captureEndpointEvent, offset: 5, team_id: 3 }, // repeat
                { ...captureEndpointEvent, offset: 6, team_id: 3, distinct_id: 'id2' },
                { ...captureEndpointEvent, offset: 7, team_id: 4 },
                { ...captureEndpointEvent, offset: 8, team_id: 5 },
                { ...captureEndpointEvent, offset: 9, team_id: 5 }, // repeat
                { ...captureEndpointEvent, offset: 10, team_id: 3, distinct_id: 'id2' }, // repeat
                { ...captureEndpointEvent, offset: 11, team_id: 8 },
                { ...captureEndpointEvent, offset: 12, team_id: 4 }, // repeat
                { ...captureEndpointEvent, offset: 13, team_id: 3 }, // repeat
                { ...captureEndpointEvent, offset: 14, team_id: 5 }, // repeat
            ])
            const tokenBlockList = buildStringMatcher('another_token,more_token', false)
            await eachBatchParallelIngestion(tokenBlockList, batch, queue, IngestionOverflowMode.Disabled)
            expect(runEventPipeline).toHaveBeenCalledTimes(14)
            expect(ingestEventBatchingInputLengthSummarySpy).toHaveBeenCalledWith(14)
            expect(ingestEventBatchingBatchCountSummarySpy).toHaveBeenCalledWith(5)
        })

        it('fails the batch if runEventPipeline rejects repeatedly', async () => {
            const tokenBlockList = buildStringMatcher('another_token,more_token', false)
            const batch = createBatch(captureEndpointEvent)
            runEventPipeline
                .mockImplementationOnce(() => Promise.reject('runEventPipeline nopes out'))
                .mockImplementationOnce(() => Promise.reject('runEventPipeline nopes out'))
                .mockImplementationOnce(() => Promise.reject('runEventPipeline nopes out'))
            await expect(
                eachBatchParallelIngestion(tokenBlockList, batch, queue, IngestionOverflowMode.Disabled)
            ).rejects.toBe('runEventPipeline nopes out')
            expect(runEventPipeline).toHaveBeenCalledTimes(3)
            runEventPipeline.mockRestore()
        })
    })
})
