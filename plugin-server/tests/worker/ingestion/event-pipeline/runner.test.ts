import { DateTime } from 'luxon'
import { v4 } from 'uuid'

import { PluginEvent } from '@posthog/plugin-scaffold'

import {
    PipelineResult,
    PipelineResultType,
    dlq,
    isDlqResult,
    isOkResult,
    isRedirectResult,
    ok,
    redirect,
} from '~/ingestion/pipelines/results'
import { forSnapshot } from '~/tests/helpers/snapshots'
import { BatchWritingGroupStoreForBatch } from '~/worker/ingestion/groups/batch-writing-group-store'
import { BatchWritingPersonsStoreForBatch } from '~/worker/ingestion/persons/batch-writing-person-store'

import { KafkaProducerWrapper, TopicMessage } from '../../../../src/kafka/producer'
import {
    ClickHouseTimestamp,
    ISOTimestamp,
    Person,
    PipelineEvent,
    PreIngestionEvent,
    ProjectId,
    RawKafkaEvent,
    Team,
} from '../../../../src/types'
import { createEventsToDropByToken } from '../../../../src/utils/db/hub'
import { parseJSON } from '../../../../src/utils/json-parse'
import { createEventStep } from '../../../../src/worker/ingestion/event-pipeline/createEventStep'
import { emitEventStep } from '../../../../src/worker/ingestion/event-pipeline/emitEventStep'
import * as metrics from '../../../../src/worker/ingestion/event-pipeline/metrics'
import { prepareEventStep } from '../../../../src/worker/ingestion/event-pipeline/prepareEventStep'
import { processPersonsStep } from '../../../../src/worker/ingestion/event-pipeline/processPersonsStep'
import { EventPipelineRunner } from '../../../../src/worker/ingestion/event-pipeline/runner'
import { PersonMergeLimitExceededError } from '../../../../src/worker/ingestion/persons/person-merge-types'
import { PostgresPersonRepository } from '../../../../src/worker/ingestion/persons/repositories/postgres-person-repository'

jest.mock('../../../../src/worker/ingestion/event-pipeline/processPersonsStep')
jest.mock('../../../../src/worker/ingestion/event-pipeline/prepareEventStep')
jest.mock('../../../../src/worker/ingestion/event-pipeline/createEventStep')
jest.mock('../../../../src/worker/ingestion/event-pipeline/emitEventStep')
jest.mock('../../../../src/worker/ingestion/event-pipeline/runAsyncHandlersStep')

class TestEventPipelineRunner extends EventPipelineRunner {
    steps: Array<string> = []
    stepsWithArgs: Array<[string, any[]]> = []

    protected async runStep<T, Step extends (...args: any[]) => Promise<T>>(
        step: Step,
        [runner, ...args]: Parameters<Step>,
        teamId: number,
        sendtoDLQ: boolean = true
    ) {
        this.steps.push(step.name)

        // We stringify+parse to clone the `args` object, since we do a lot of event mutation
        // and pass the same object around by reference. We want to see a "snapshot" of the args
        // sent to each step, rather than the final mutated object (which many steps actually share
        // in practice, for better or worse).
        this.stepsWithArgs.push([step.name, parseJSON(JSON.stringify(args))])

        return super.runStep<T, Step>(step, [runner, ...args] as Parameters<Step>, teamId, sendtoDLQ)
    }

    protected async runPipelineStep<T, Step extends (...args: any[]) => Promise<PipelineResult<T>>>(
        step: Step,
        args: Parameters<Step>,
        teamId: number,
        sendtoDLQ: boolean = true
    ) {
        this.steps.push(step.name)

        // We stringify+parse to clone the `args` object, since we do a lot of event mutation
        // and pass the same object around by reference. We want to see a "snapshot" of the args
        // sent to each step, rather than the final mutated object (which many steps actually share
        // in practice, for better or worse).
        const [runner, ...restArgs] = args
        this.stepsWithArgs.push([step.name, parseJSON(JSON.stringify(restArgs))])

        return super.runPipelineStep<T, Step>(step, [runner, ...args] as Parameters<Step>, teamId, sendtoDLQ)
    }
}

const team = {
    id: 2,
    person_processing_opt_out: false,
    api_token: 'token1',
    project_id: 2 as ProjectId,
    organization_id: '2',
    uuid: v4(),
    name: '2',
    anonymize_ips: true,
    slack_incoming_webhook: 'slack_incoming_webhook',
    session_recording_opt_in: true,
    heatmaps_opt_in: null,
    ingested_event: true,
    person_display_name_properties: null,
    test_account_filters: null,
    cookieless_server_hash_mode: null,
    timezone: 'UTC',
    available_features: [],
    drop_events_older_than_seconds: null,
} as Team

const pipelineEvent: PipelineEvent = {
    distinct_id: 'my_id',
    ip: '127.0.0.1',
    site_url: 'http://localhost',
    team_id: null,
    token: 'token1',
    now: '2020-02-23T02:15:00.000Z',
    timestamp: '2020-02-23T02:15:00.000Z',
    event: 'default event',
    properties: {},
    uuid: 'uuid1',
}

const pluginEvent: PluginEvent = {
    distinct_id: 'my_id',
    ip: '127.0.0.1',
    site_url: 'http://localhost',
    team_id: 2,
    now: '2020-02-23T02:15:00.000Z',
    timestamp: '2020-02-23T02:15:00.000Z',
    event: 'default event',
    properties: {},
    uuid: 'uuid1',
}

const preIngestionEvent: PreIngestionEvent = {
    eventUuid: 'uuid1',
    distinctId: 'my_id',
    teamId: 2,
    projectId: 1 as ProjectId,
    timestamp: '2020-02-23T02:15:00.000Z' as ISOTimestamp,
    event: '$pageview',
    properties: {},

    // @ts-expect-error TODO: Check if elementsList and ip are necessary
    elementsList: [],
    ip: '127.0.0.1',
}

const createdEvent: RawKafkaEvent = {
    created_at: '2024-11-18 14:54:33.606' as ClickHouseTimestamp,
    distinct_id: 'my_id',
    elements_chain: '',
    event: '$pageview',
    person_created_at: '2024-11-18 14:54:33' as ClickHouseTimestamp,
    person_mode: 'full',
    person_properties: '{}',
    project_id: 1 as ProjectId,
    properties: '{}',
    team_id: 2,
    timestamp: '2020-02-23 02:15:00.000' as ClickHouseTimestamp,
    uuid: 'uuid1',
}

const person: Person = {
    // @ts-expect-error TODO: Check if we need to pass id in here
    id: 123,
    team_id: 2,
    properties: {},
    is_user_id: 0,
    is_identified: true,
    uuid: 'uuid',
    properties_last_updated_at: {},
    properties_last_operation: {},
    created_at: DateTime.fromISO(pluginEvent.timestamp!).toUTC(),
    version: 0,
}

describe('EventPipelineRunner', () => {
    let runner: TestEventPipelineRunner
    let hub: any

    const mockProducer: jest.Mocked<KafkaProducerWrapper> = {
        queueMessages: jest.fn() as any,
        produce: jest.fn() as any,
    } as any

    beforeEach(() => {
        jest.mocked(mockProducer.queueMessages).mockImplementation(() => Promise.resolve())
        jest.mocked(mockProducer.produce).mockImplementation(() => Promise.resolve())

        hub = {
            kafkaProducer: mockProducer,
            teamManager: {
                fetchTeam: jest.fn(() => Promise.resolve(team)),
            },
            db: {
                kafkaProducer: mockProducer,
                fetchPerson: jest.fn(),
            },
            eventsToDropByToken: createEventsToDropByToken('drop_token:drop_id,drop_token_all:*'),
            TIMESTAMP_COMPARISON_LOGGING_SAMPLE_RATE: 0.0,
        }

        const personsStoreForBatch = new BatchWritingPersonsStoreForBatch(
            new PostgresPersonRepository(hub.db.postgres),
            hub.kafkaProducer
        )
        const groupStoreForBatch = new BatchWritingGroupStoreForBatch(
            hub.db,
            hub.groupRepository,
            hub.clickhouseGroupRepository
        )
        runner = new TestEventPipelineRunner(
            hub,
            pluginEvent,
            undefined,
            personsStoreForBatch,
            groupStoreForBatch,
            undefined // headers
        )

        jest.mocked(processPersonsStep).mockResolvedValue(
            ok([
                pluginEvent,
                { person, personUpdateProperties: {}, get: () => Promise.resolve(person) } as any,
                Promise.resolve(),
            ])
        )
        jest.mocked(prepareEventStep).mockResolvedValue(preIngestionEvent)

        jest.mocked(createEventStep).mockResolvedValue(createdEvent)

        jest.mocked(emitEventStep).mockResolvedValue([Promise.resolve()])
    })

    describe('runEventPipeline()', () => {
        it('runs steps', async () => {
            await runner.runEventPipeline(pluginEvent, team)

            expect(runner.steps).toEqual([
                'dropOldEventsStep',
                'transformEventStep',
                'normalizeEventStep',
                'processPersonsStep',
                'prepareEventStep',
                'extractHeatmapDataStep',
                'createEventStep',
                'emitEventStep',
            ])
            expect(forSnapshot(runner.stepsWithArgs)).toMatchSnapshot()
        })

        it('emits metrics for every step', async () => {
            const eventProcessedAndIngestedCounterSpy = jest.spyOn(metrics.eventProcessedAndIngestedCounter, 'inc')
            const pipelineStepMsSummarySpy = jest.spyOn(metrics.pipelineStepMsSummary, 'labels')
            const pipelineStepErrorCounterSpy = jest.spyOn(metrics.pipelineStepErrorCounter, 'labels')

            const result = await runner.runEventPipeline(pluginEvent, team)
            expect(isOkResult(result)).toBe(true)
            if (isOkResult(result)) {
                expect(result.value.error).toBeUndefined()
            }

            expect(pipelineStepMsSummarySpy).toHaveBeenCalledTimes(8)
            expect(eventProcessedAndIngestedCounterSpy).toHaveBeenCalledTimes(1)
            expect(pipelineStepMsSummarySpy).toHaveBeenCalledWith('emitEventStep')
            expect(pipelineStepErrorCounterSpy).not.toHaveBeenCalled()
        })

        describe('errors during processing', () => {
            const error = new Error('testError')

            it('runs and increments metrics', async () => {
                const pipelineStepMsSummarySpy = jest.spyOn(metrics.pipelineStepMsSummary, 'labels')
                const pipelineLastStepCounterSpy = jest.spyOn(metrics.pipelineLastStepCounter, 'labels')
                const pipelineStepErrorCounterSpy = jest.spyOn(metrics.pipelineStepErrorCounter, 'labels')

                jest.mocked(prepareEventStep).mockRejectedValue(error)

                await runner.runEventPipeline(pluginEvent, team)

                expect(pipelineStepMsSummarySpy).not.toHaveBeenCalledWith('prepareEventStep')
                expect(pipelineLastStepCounterSpy).not.toHaveBeenCalled()
                expect(pipelineStepErrorCounterSpy).toHaveBeenCalledWith('prepareEventStep')
            })

            it('emits DLQ when merge limit is exceeded during processPersonsStep', async () => {
                // Make processPersonsStep return a DLQ result instead of throwing
                jest.mocked(processPersonsStep).mockResolvedValueOnce(
                    dlq('Merge limit exceeded', new PersonMergeLimitExceededError('person_merge_move_limit_hit'))
                )

                const result = await runner.runEventPipeline(pluginEvent, team)

                // Verify that the pipeline returned a DLQ result
                expect(result.type).toBe(PipelineResultType.DLQ)
                if (isDlqResult(result)) {
                    expect(result.reason).toBe('Merge limit exceeded')
                    expect(result.error).toBeInstanceOf(PersonMergeLimitExceededError)
                }
            })

            it('redirects event when merge limit is exceeded in async mode during processPersonsStep', async () => {
                // Make processPersonsStep return a redirect result
                jest.mocked(processPersonsStep).mockResolvedValueOnce(
                    redirect('Event redirected to async merge topic', 'async-merge-topic')
                )

                const result = await runner.runEventPipeline(pluginEvent, team)

                // Verify that the pipeline returned a redirect result
                expect(result.type).toBe(PipelineResultType.REDIRECT)
                if (isRedirectResult(result)) {
                    expect(result.reason).toBe('Event redirected to async merge topic')
                    expect(result.topic).toBe('async-merge-topic')
                }
            })
        })

        describe('client ingestion error event', () => {
            it('drops events and adds a warning for special $$client_ingestion_warning event', async () => {
                const event = {
                    ...pipelineEvent,
                    properties: { $$client_ingestion_warning_message: 'My warning message!' },
                    event: '$$client_ingestion_warning',
                    team_id: 9,
                }
                const team9: Team = {
                    ...team,
                    id: 9,
                }

                await runner.runEventPipeline(event, team9)
                expect(runner.steps).toEqual([])
                expect(mockProducer.queueMessages).toHaveBeenCalledTimes(1)
                expect(
                    parseJSON((mockProducer.queueMessages.mock.calls[0][0] as TopicMessage).messages[0].value as string)
                ).toMatchObject({
                    team_id: 9,
                    type: 'client_ingestion_warning',
                    details: JSON.stringify({
                        eventUuid: 'uuid1',
                        event: '$$client_ingestion_warning',
                        distinctId: 'my_id',
                        message: 'My warning message!',
                    }),
                })
            })
        })

        describe('$$heatmap events', () => {
            let heatmapEvent: PluginEvent
            beforeEach(() => {
                heatmapEvent = {
                    ...pipelineEvent,
                    event: '$$heatmap',
                    properties: {
                        ...pipelineEvent.properties,
                        $heatmap_data: {
                            url1: ['data'],
                            url2: ['more data'],
                        },
                    },
                    team_id: 2,
                }

                // setup just enough mocks that the right pipeline runs

                const personsStore = new BatchWritingPersonsStoreForBatch(
                    new PostgresPersonRepository(hub.db.postgres),
                    hub.kafkaProducer
                )
                const groupStoreForBatch = new BatchWritingGroupStoreForBatch(
                    hub.db,
                    hub.groupRepository,
                    hub.clickhouseGroupRepository
                )
                runner = new TestEventPipelineRunner(
                    hub,
                    heatmapEvent,
                    undefined,
                    personsStore,
                    groupStoreForBatch,
                    undefined // headers
                )

                const heatmapPreIngestionEvent = {
                    ...preIngestionEvent,
                    event: '$$heatmap',
                    properties: {
                        ...heatmapEvent.properties,
                    },
                }
                jest.mocked(prepareEventStep).mockResolvedValue(heatmapPreIngestionEvent)
            })

            it('runs the expected steps for heatmap_data', async () => {
                await runner.runEventPipeline(heatmapEvent, team)

                expect(runner.steps).toEqual(['normalizeEventStep', 'prepareEventStep', 'extractHeatmapDataStep'])
            })
        })
    })

    describe('EventPipelineRunner $process_person_profile=false', () => {
        it.each(['$identify', '$create_alias', '$merge_dangerously', '$groupidentify'])(
            'drops event %s that are not allowed when $process_person_profile=false',
            async (eventName) => {
                const event = {
                    ...pipelineEvent,
                    properties: { $process_person_profile: false },
                    event: eventName,
                    team_id: 9,
                }
                const team9: Team = {
                    ...team,
                    id: 9,
                }

                await runner.runEventPipeline(event, team9)
                expect(runner.steps).toEqual([])
                expect(mockProducer.queueMessages).toHaveBeenCalledTimes(1)
                expect(
                    parseJSON((mockProducer.queueMessages.mock.calls[0][0] as TopicMessage).messages[0].value as string)
                ).toMatchObject({
                    team_id: 9,
                    type: 'invalid_event_when_process_person_profile_is_false',
                    details: JSON.stringify({ eventUuid: 'uuid1', event: eventName, distinctId: 'my_id' }),
                })
            }
        )
    })
})
