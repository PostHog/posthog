import { buildIntegerMatcher } from '../../../src/config/config'
import { KAFKA_EVENTS_PLUGIN_INGESTION } from '../../../src/config/kafka-topics'
import {
    eachBatchParallelIngestion,
    IngestionOverflowMode,
    splitIngestionBatch,
} from '../../../src/main/ingestion-queues/batch-processing/each-batch-ingestion'
import { eachBatchAppsOnEventHandlers } from '../../../src/main/ingestion-queues/batch-processing/each-batch-onevent'
import {
    eachBatchWebhooksHandlers,
    groupIntoBatchesByUsage,
} from '../../../src/main/ingestion-queues/batch-processing/each-batch-webhooks'
import {
    ClickHouseTimestamp,
    ClickHouseTimestampSecondPrecision,
    ISOTimestamp,
    PostIngestionEvent,
    RawClickHouseEvent,
} from '../../../src/types'
import { ActionManager } from '../../../src/worker/ingestion/action-manager'
import { ActionMatcher } from '../../../src/worker/ingestion/action-matcher'
import { HookCommander } from '../../../src/worker/ingestion/hooks'
import { runOnEvent } from '../../../src/worker/plugins/run'
import { pluginConfig39 } from '../../helpers/plugins'

jest.mock('../../../src/worker/plugins/run')

jest.mock('../../../src/worker/ingestion/event-pipeline/runAsyncHandlersStep', () => {
    const originalModule = jest.requireActual('../../../src/worker/ingestion/event-pipeline/runAsyncHandlersStep')
    return {
        ...originalModule,
        processWebhooksStep: jest.fn(originalModule.processWebhooksStep),
    }
})
jest.mock('../../../src/utils/status')
jest.mock('./../../../src/worker/ingestion/utils')
jest.mock('./../../../src/worker/ingestion/event-pipeline/runner', () => ({
    runEventPipeline: jest.fn().mockResolvedValue('default value'),
    // runEventPipeline: jest.fn().mockRejectedValue('default value'),
}))
import { runEventPipeline } from './../../../src/worker/ingestion/event-pipeline/runner'

const event: PostIngestionEvent = {
    eventUuid: 'uuid1',
    distinctId: 'my_id',
    teamId: 2,
    timestamp: '2020-02-23T02:15:00.000Z' as ISOTimestamp,
    event: '$pageview',
    properties: {},
    elementsList: [],
    person_id: 'F99FA0A1-E0C2-4CFE-A09A-4C3C4327A4CC',
    person_created_at: '2020-02-20T02:15:00.000Z' as ISOTimestamp,
    person_properties: {},
}

const clickhouseEvent: RawClickHouseEvent = {
    event: '$pageview',
    properties: JSON.stringify({
        $ip: '127.0.0.1',
    }),
    uuid: 'uuid1',
    elements_chain: '',
    timestamp: '2020-02-23 02:15:00.00' as ClickHouseTimestamp,
    team_id: 2,
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
                WORKER_CONCURRENCY: 1,
                TASKS_PER_WORKER: 10,
                INGESTION_CONCURRENCY: 4,
                BUFFER_CONVERSION_SECONDS: 60,
                statsd: {
                    timing: jest.fn(),
                    increment: jest.fn(),
                    histogram: jest.fn(),
                    gauge: jest.fn(),
                },
                kafkaProducer: {
                    queueMessage: jest.fn(),
                },
                pluginConfigsPerTeam: new Map(),
            },
        }
    })

    describe('eachBatchAppsOnEventHandlers', () => {
        it('calls runOnEvent when useful', async () => {
            queue.pluginsServer.pluginConfigsPerTeam.set(2, [pluginConfig39])
            await eachBatchAppsOnEventHandlers(createKafkaJSBatch(clickhouseEvent), queue)
            // TODO fix to jest spy on the actual function
            expect(runOnEvent).toHaveBeenCalledWith(
                expect.anything(),
                expect.objectContaining({
                    uuid: 'uuid1',
                    team_id: 2,
                    distinct_id: 'my_id',
                })
            )
            expect(queue.pluginsServer.statsd.timing).toHaveBeenCalledWith(
                'kafka_queue.each_batch_async_handlers_on_event',
                expect.any(Date)
            )
        })
        it('skip runOnEvent when no pluginconfig for team', async () => {
            queue.pluginsServer.pluginConfigsPerTeam.clear()
            await eachBatchAppsOnEventHandlers(createKafkaJSBatch(clickhouseEvent), queue)
            expect(runOnEvent).not.toHaveBeenCalled()
            expect(queue.pluginsServer.statsd.timing).toHaveBeenCalledWith(
                'kafka_queue.each_batch_async_handlers_on_event',
                expect.any(Date)
            )
        })
        it('parses elements when useful', async () => {
            queue.pluginsServer.pluginConfigsPerTeam.set(2, [
                { ...pluginConfig39, plugin_id: 60 },
                { ...pluginConfig39, plugin_id: 33 },
            ])
            queue.pluginsServer.pluginConfigsToSkipElementsParsing = buildIntegerMatcher('12,60,100', true)
            await eachBatchAppsOnEventHandlers(
                createKafkaJSBatch({ ...clickhouseEvent, elements_chain: 'random' }),
                queue
            )
            expect(runOnEvent).toHaveBeenCalledWith(
                expect.anything(),
                expect.objectContaining({
                    uuid: 'uuid1',
                    team_id: 2,
                    distinct_id: 'my_id',
                    elements: [{ attributes: {}, order: 0, tag_name: 'random' }],
                })
            )
        })
        it('skips elements parsing when not useful', async () => {
            queue.pluginsServer.pluginConfigsPerTeam.set(2, [
                { ...pluginConfig39, plugin_id: 60 },
                { ...pluginConfig39, plugin_id: 100 },
            ])
            queue.pluginsServer.pluginConfigsToSkipElementsParsing = buildIntegerMatcher('12,60,100', true)
            await eachBatchAppsOnEventHandlers(
                createKafkaJSBatch({ ...clickhouseEvent, elements_chain: 'random' }),
                queue
            )
            expect(runOnEvent).toHaveBeenCalledWith(
                expect.anything(),
                expect.objectContaining({
                    uuid: 'uuid1',
                    team_id: 2,
                    distinct_id: 'my_id',
                    elements: [],
                })
            )
        })
    })

    describe('eachBatchWebhooksHandlers', () => {
        it('calls runWebhooksHandlersEventPipeline', async () => {
            const actionManager = new ActionManager(queue.pluginsServer.postgres)
            const actionMatcher = new ActionMatcher(queue.pluginsServer.postgres, actionManager)
            const hookCannon = new HookCommander(
                queue.pluginsServer.postgres,
                queue.pluginsServer.teamManager,
                queue.pluginsServer.organizationManager,
                new Set(),
                queue.pluginsServer.appMetrics,
                undefined,
                queue.pluginsServer.EXTERNAL_REQUEST_TIMEOUT_MS
            )
            const matchSpy = jest.spyOn(actionMatcher, 'match')
            // mock hasWebhooks to return true
            actionMatcher.hasWebhooks = jest.fn(() => true)
            await eachBatchWebhooksHandlers(
                createKafkaJSBatch(clickhouseEvent),
                actionMatcher,
                hookCannon,
                queue.pluginsServer.statsd,
                10
            )

            // NOTE: really it would be nice to verify that fire has been called
            // on hookCannon, but that would require a little more setup, and it
            // is at the least testing a little bit more than we were before.
            expect(matchSpy).toHaveBeenCalledWith(
                {
                    ...event,
                    properties: {
                        $ip: '127.0.0.1',
                    },
                },
                []
            )
            expect(queue.pluginsServer.statsd.timing).toHaveBeenCalledWith(
                'kafka_queue.each_batch_async_handlers_webhooks',
                expect.any(Date)
            )
        })

        it('it batches events properly', () => {
            // create a batch with 10 events each having teamId the same as offset, timestamp which all increment by 1
            const batch = createKafkaJSBatchWithMultipleEvents([
                {
                    ...clickhouseEvent,
                    team_id: 1,
                    offset: 1,
                    kafkaTimestamp: '2020-02-23 00:01:00.00' as ClickHouseTimestamp,
                },
                {
                    ...clickhouseEvent,
                    team_id: 2,
                    offset: 2,
                    kafkaTimestamp: '2020-02-23 00:02:00.00' as ClickHouseTimestamp,
                },
                {
                    ...clickhouseEvent,
                    team_id: 3,
                    offset: 3,
                    kafkaTimestamp: '2020-02-23 00:03:00.00' as ClickHouseTimestamp,
                },
                {
                    ...clickhouseEvent,
                    team_id: 4,
                    offset: 4,
                    kafkaTimestamp: '2020-02-23 00:04:00.00' as ClickHouseTimestamp,
                },
                {
                    ...clickhouseEvent,
                    team_id: 5,
                    offset: 5,
                    kafkaTimestamp: '2020-02-23 00:05:00.00' as ClickHouseTimestamp,
                },
                {
                    ...clickhouseEvent,
                    team_id: 6,
                    offset: 6,
                    kafkaTimestamp: '2020-02-23 00:06:00.00' as ClickHouseTimestamp,
                },
                {
                    ...clickhouseEvent,
                    team_id: 7,
                    offset: 7,
                    kafkaTimestamp: '2020-02-23 00:07:00.00' as ClickHouseTimestamp,
                },
                {
                    ...clickhouseEvent,
                    team_id: 8,
                    offset: 8,
                    kafkaTimestamp: '2020-02-23 00:08:00.00' as ClickHouseTimestamp,
                },
                {
                    ...clickhouseEvent,
                    team_id: 9,
                    offset: 9,
                    kafkaTimestamp: '2020-02-23 00:09:00.00' as ClickHouseTimestamp,
                },
                {
                    ...clickhouseEvent,
                    team_id: 10,
                    offset: 10,
                    kafkaTimestamp: '2020-02-23 00:10:00.00' as ClickHouseTimestamp,
                },
            ])
            // teamIDs 1,3,10 should return false, others true
            const toProcess = jest.fn((teamId) => teamId !== 1 && teamId !== 3 && teamId !== 10)
            const result = groupIntoBatchesByUsage(batch.batch.messages, 5, toProcess)
            expect(result).toEqual([
                {
                    eventBatch: expect.arrayContaining([
                        expect.objectContaining({
                            team_id: 2,
                        }),
                        expect.objectContaining({
                            team_id: 4,
                        }),
                        expect.objectContaining({
                            team_id: 5,
                        }),
                        expect.objectContaining({
                            team_id: 6,
                        }),
                        expect.objectContaining({
                            team_id: 7,
                        }),
                    ]),
                    lastOffset: 7,
                    lastTimestamp: '2020-02-23 00:07:00.00' as ClickHouseTimestamp,
                },
                {
                    eventBatch: expect.arrayContaining([
                        expect.objectContaining({
                            team_id: 8,
                        }),
                        expect.objectContaining({
                            team_id: 9,
                        }),
                    ]),
                    lastOffset: 10,
                    lastTimestamp: '2020-02-23 00:10:00.00' as ClickHouseTimestamp,
                },
            ])
            // make sure that if the last message would be a new batch and if it's going to be excluded we
            // still get the last batch as empty with the right offsite and timestamp
            const result2 = groupIntoBatchesByUsage(batch.batch.messages, 7, toProcess)
            expect(result2).toEqual([
                {
                    eventBatch: expect.arrayContaining([
                        expect.objectContaining({
                            team_id: 2,
                        }),
                        expect.objectContaining({
                            team_id: 4,
                        }),
                        expect.objectContaining({
                            team_id: 5,
                        }),
                        expect.objectContaining({
                            team_id: 6,
                        }),
                        expect.objectContaining({
                            team_id: 7,
                        }),
                        expect.objectContaining({
                            team_id: 8,
                        }),
                        expect.objectContaining({
                            team_id: 9,
                        }),
                    ]),
                    lastOffset: 9,
                    lastTimestamp: '2020-02-23 00:09:00.00' as ClickHouseTimestamp,
                },
                {
                    eventBatch: expect.arrayContaining([]),
                    lastOffset: 10,
                    lastTimestamp: '2020-02-23 00:10:00.00' as ClickHouseTimestamp,
                },
            ])
        })
    })

    describe('eachBatchParallelIngestion', () => {
        let runEventPipelineSpy
        beforeEach(() => {
            runEventPipelineSpy = jest.spyOn(
                require('./../../../src/worker/ingestion/event-pipeline/runner'),
                'runEventPipeline'
            )
        })
        it('calls runEventPipeline', async () => {
            const batch = createBatch(captureEndpointEvent)
            await eachBatchParallelIngestion(batch, queue, IngestionOverflowMode.Disabled)

            expect(runEventPipeline).toHaveBeenCalledWith(expect.anything(), {
                distinct_id: 'id',
                event: 'event',
                properties: {},
                ip: null,
                now: null,
                sent_at: null,
                site_url: null,
                team_id: 1,
                uuid: 'uuid1',
            })
            expect(queue.pluginsServer.statsd.timing).toHaveBeenCalledWith(
                'kafka_queue.each_batch_parallel_ingestion',
                expect.any(Date)
            )
        })

        it("doesn't fail the batch if runEventPipeline rejects once then succeeds on retry", async () => {
            const batch = createBatch(captureEndpointEvent)
            runEventPipelineSpy.mockImplementationOnce(() => Promise.reject('runEventPipeline nopes out'))
            await eachBatchParallelIngestion(batch, queue, IngestionOverflowMode.Disabled)
            expect(runEventPipeline).toHaveBeenCalledTimes(2)
        })

        it('fails the batch if one deferred promise rejects', async () => {
            const batch = createBatch(captureEndpointEvent)
            runEventPipelineSpy.mockImplementationOnce(() =>
                Promise.resolve({
                    promises: [Promise.resolve(), Promise.reject('deferred nopes out')],
                })
            )
            await expect(eachBatchParallelIngestion(batch, queue, IngestionOverflowMode.Disabled)).rejects.toBe(
                'deferred nopes out'
            )
            expect(runEventPipeline).toHaveBeenCalledTimes(1)
        })

        it('batches events by team or token and distinct_id', () => {
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
            for (const group of splitIngestionBatch(batch, IngestionOverflowMode.Disabled).toProcess) {
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
        })

        it('does not batch events when consuming overflow', () => {
            const input = createBatchWithMultipleEvents([
                { ...captureEndpointEvent, team_id: 3, distinct_id: 'a' },
                { ...captureEndpointEvent, team_id: 3, distinct_id: 'a' },
                { ...captureEndpointEvent, team_id: 3, distinct_id: 'b' },
                { ...captureEndpointEvent, team_id: 4, distinct_id: 'a' },
                { ...captureEndpointEvent, team_id: 4, distinct_id: 'a' },
            ])
            const batches = splitIngestionBatch(input, IngestionOverflowMode.Consume).toProcess
            expect(batches.length).toEqual(input.length)
            for (const group of batches) {
                expect(group.length).toEqual(1)
            }
        })

        it('batches events but commits offsets only once', async () => {
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

            await eachBatchParallelIngestion(batch, queue, IngestionOverflowMode.Disabled)
            expect(runEventPipeline).toHaveBeenCalledTimes(14)
            expect(queue.pluginsServer.statsd.histogram).toHaveBeenCalledWith(
                'ingest_event_batching.input_length',
                14,
                {
                    key: 'ingestion',
                }
            )
            expect(queue.pluginsServer.statsd.histogram).toHaveBeenCalledWith('ingest_event_batching.batch_count', 5, {
                key: 'ingestion',
            })
        })

        it('fails the batch if runEventPipeline rejects repeatedly', async () => {
            const batch = createBatch(captureEndpointEvent)
            runEventPipelineSpy
                .mockImplementationOnce(() => Promise.reject('runEventPipeline nopes out'))
                .mockImplementationOnce(() => Promise.reject('runEventPipeline nopes out'))
                .mockImplementationOnce(() => Promise.reject('runEventPipeline nopes out'))
            await expect(eachBatchParallelIngestion(batch, queue, IngestionOverflowMode.Disabled)).rejects.toBe(
                'runEventPipeline nopes out'
            )
            expect(runEventPipeline).toHaveBeenCalledTimes(3)
            runEventPipelineSpy.mockRestore()
        })
    })
})
