import { PostgresRouter } from '~/utils/db/postgres'
import { TeamManager } from '~/utils/team-manager'

import {
    eachBatchWebhooksHandlers,
    groupIntoBatchesByUsage,
} from '../../../src/main/ingestion-queues/batch-processing/each-batch-webhooks'
import {
    ClickHouseTimestamp,
    ClickHouseTimestampSecondPrecision,
    ISOTimestamp,
    PostIngestionEvent,
    ProjectId,
    RawKafkaEvent,
} from '../../../src/types'
import { ActionManager } from '../../../src/worker/ingestion/action-manager'
import { ActionMatcher } from '../../../src/worker/ingestion/action-matcher'
import { GroupTypeManager } from '../../../src/worker/ingestion/group-type-manager'
import { HookCommander } from '../../../src/worker/ingestion/hooks'

jest.mock('../../../src/worker/plugins/run')

jest.mock('../../../src/worker/ingestion/event-pipeline/runAsyncHandlersStep', () => {
    const originalModule = jest.requireActual('../../../src/worker/ingestion/event-pipeline/runAsyncHandlersStep')
    return {
        ...originalModule,
        processWebhooksStep: jest.fn(originalModule.processWebhooksStep),
    }
})
jest.mock('../../../src/utils/logger')
jest.mock('./../../../src/worker/ingestion/utils')

const runEventPipeline = jest.fn().mockResolvedValue('default value')

jest.mock('./../../../src/worker/ingestion/event-pipeline/runner', () => ({
    EventPipelineRunner: jest.fn().mockImplementation(() => ({
        runEventPipeline: runEventPipeline,
    })),
}))

const event: PostIngestionEvent = {
    eventUuid: 'uuid1',
    distinctId: 'my_id',
    teamId: 2,
    projectId: 1 as ProjectId,
    timestamp: '2020-02-23T02:15:00.000Z' as ISOTimestamp,
    event: '$pageview',
    properties: {},
    elementsList: undefined,
    person_id: 'F99FA0A1-E0C2-4CFE-A09A-4C3C4327A4CC',
    person_created_at: '2020-02-20T02:15:00.000Z' as ISOTimestamp,
    person_properties: {},
}

// @ts-expect-error TODO: Fix add `person_mode` to this
const kafkaEvent: RawKafkaEvent = {
    event: '$pageview',
    properties: JSON.stringify({
        $ip: '127.0.0.1',
    }),
    uuid: 'uuid1',
    elements_chain: '',
    timestamp: '2020-02-23 02:15:00.00' as ClickHouseTimestamp,
    team_id: 2,
    project_id: 1 as ProjectId,
    distinct_id: 'my_id',
    created_at: '2020-02-23 02:15:00.00' as ClickHouseTimestamp,
    person_id: 'F99FA0A1-E0C2-4CFE-A09A-4C3C4327A4CC',
    person_created_at: '2020-02-20 02:15:00' as ClickHouseTimestampSecondPrecision, // Match createEvent ts format
    person_properties: '{}',
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
                pubSub: {
                    on: jest.fn(),
                },
            },
        }
    })

    describe('eachBatchWebhooksHandlers', () => {
        it('calls runWebhooksHandlersEventPipeline', async () => {
            const actionManager = new ActionManager(queue.pluginsServer.postgres, queue.pluginsServer.pubSub)
            const actionMatcher = new ActionMatcher(queue.pluginsServer.postgres, actionManager)
            const hookCannon = new HookCommander(
                queue.pluginsServer.postgres,
                queue.pluginsServer.teamManager,
                queue.pluginsServer.rustyHook,
                queue.pluginsServer.appMetrics,
                queue.pluginsServer.EXTERNAL_REQUEST_TIMEOUT_MS
            )
            const groupTypeManager: GroupTypeManager = {
                fetchGroupTypes: jest.fn(() => Promise.resolve({})),
            } as unknown as GroupTypeManager
            const teamManager: TeamManager = {
                hasAvailableFeature: jest.fn(() => Promise.resolve(true)),
            } as unknown as TeamManager

            const matchSpy = jest.spyOn(actionMatcher, 'match')
            // mock hasWebhooks to return true
            actionMatcher.hasWebhooks = jest.fn(() => true)
            await eachBatchWebhooksHandlers(
                createKafkaJSBatch(kafkaEvent),
                actionMatcher,
                hookCannon,
                10,
                groupTypeManager,
                teamManager,

                // @ts-expect-error this is not being used in the function, so just passing null here
                null as PostgresRouter
            )

            // NOTE: really it would be nice to verify that fire has been called
            // on hookCannon, but that would require a little more setup, and it
            // is at the least testing a little bit more than we were before.
            expect(matchSpy).toHaveBeenCalledWith({
                ...event,
                groups: {},
                properties: {
                    $ip: '127.0.0.1',
                },
            })
        })

        it('it batches events properly', () => {
            // create a batch with 10 events each having teamId the same as offset, timestamp which all increment by 1
            const batch = createKafkaJSBatchWithMultipleEvents([
                {
                    ...kafkaEvent,
                    team_id: 1,
                    offset: 1,
                    kafkaTimestamp: '2020-02-23 00:01:00.00' as ClickHouseTimestamp,
                },
                {
                    ...kafkaEvent,
                    team_id: 2,
                    offset: 2,
                    kafkaTimestamp: '2020-02-23 00:02:00.00' as ClickHouseTimestamp,
                },
                {
                    ...kafkaEvent,
                    team_id: 3,
                    offset: 3,
                    kafkaTimestamp: '2020-02-23 00:03:00.00' as ClickHouseTimestamp,
                },
                {
                    ...kafkaEvent,
                    team_id: 4,
                    offset: 4,
                    kafkaTimestamp: '2020-02-23 00:04:00.00' as ClickHouseTimestamp,
                },
                {
                    ...kafkaEvent,
                    team_id: 5,
                    offset: 5,
                    kafkaTimestamp: '2020-02-23 00:05:00.00' as ClickHouseTimestamp,
                },
                {
                    ...kafkaEvent,
                    team_id: 6,
                    offset: 6,
                    kafkaTimestamp: '2020-02-23 00:06:00.00' as ClickHouseTimestamp,
                },
                {
                    ...kafkaEvent,
                    team_id: 7,
                    offset: 7,
                    kafkaTimestamp: '2020-02-23 00:07:00.00' as ClickHouseTimestamp,
                },
                {
                    ...kafkaEvent,
                    team_id: 8,
                    offset: 8,
                    kafkaTimestamp: '2020-02-23 00:08:00.00' as ClickHouseTimestamp,
                },
                {
                    ...kafkaEvent,
                    team_id: 9,
                    offset: 9,
                    kafkaTimestamp: '2020-02-23 00:09:00.00' as ClickHouseTimestamp,
                },
                {
                    ...kafkaEvent,
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
})
