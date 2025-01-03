import { PluginEvent } from '@posthog/plugin-scaffold'
import { DateTime } from 'luxon'

import { KafkaProducerWrapper } from '../../../../src/kafka/producer'
import { ISOTimestamp, Person, PipelineEvent, PreIngestionEvent, RawKafkaEvent } from '../../../../src/types'
import { createEventsToDropByToken } from '../../../../src/utils/db/hub'
import { createEventStep } from '../../../../src/worker/ingestion/event-pipeline/createEventStep'
import { emitEventStep } from '../../../../src/worker/ingestion/event-pipeline/emitEventStep'
import * as metrics from '../../../../src/worker/ingestion/event-pipeline/metrics'
import { pluginsProcessEventStep } from '../../../../src/worker/ingestion/event-pipeline/pluginsProcessEventStep'
import { populateTeamDataStep } from '../../../../src/worker/ingestion/event-pipeline/populateTeamDataStep'
import { prepareEventStep } from '../../../../src/worker/ingestion/event-pipeline/prepareEventStep'
import { processPersonsStep } from '../../../../src/worker/ingestion/event-pipeline/processPersonsStep'
import { EventPipelineRunner, StepResult } from '../../../../src/worker/ingestion/event-pipeline/runner'
import { EventsProcessor } from '../../../../src/worker/ingestion/process-event'

jest.mock('../../../../src/worker/ingestion/event-pipeline/populateTeamDataStep')
jest.mock('../../../../src/worker/ingestion/event-pipeline/pluginsProcessEventStep')
jest.mock('../../../../src/worker/ingestion/event-pipeline/processPersonsStep')
jest.mock('../../../../src/worker/ingestion/event-pipeline/prepareEventStep')
jest.mock('../../../../src/worker/ingestion/event-pipeline/createEventStep')
jest.mock('../../../../src/worker/ingestion/event-pipeline/emitEventStep')
jest.mock('../../../../src/worker/ingestion/event-pipeline/runAsyncHandlersStep')

class TestEventPipelineRunner extends EventPipelineRunner {
    steps: Array<string> = []
    stepsWithArgs: Array<[string, any[]]> = []

    protected runStep<Step extends (...args: any[]) => Promise<StepResult<any>>>(
        step: Step,
        args: Parameters<Step>,
        teamId: number,
        sentToDql = true
    ): ReturnType<Step> {
        this.steps.push(step.name)

        // We stringify+parse to clone the `args` object, since we do a lot of event mutation
        // and pass the same object around by reference. We want to see a "snapshot" of the args
        // sent to each step, rather than the final mutated object (which many steps actually share
        // in practice, for better or worse).

        const argsCopy = JSON.parse(JSON.stringify(args))

        // If it looks like the this object, replace it with a placeholder
        if (args[0] === this) {
            argsCopy[0] = '__this__'
        }

        this.stepsWithArgs.push([step.name, argsCopy])

        return super.runStep(step, args, teamId, sentToDql)
    }
}

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
    ip: '127.0.0.1',
    teamId: 2,
    projectId: 1,
    timestamp: '2020-02-23T02:15:00.000Z' as ISOTimestamp,
    event: '$pageview',
    properties: {},
    elementsList: [],
}

const createdEvent: RawKafkaEvent = {
    created_at: '2024-11-18 14:54:33.606',
    distinct_id: 'my_id',
    elements_chain: '',
    event: '$pageview',
    person_created_at: '2024-11-18 14:54:33',
    person_mode: 'full',
    person_properties: '{}',
    project_id: 1,
    properties: '{}',
    team_id: 2,
    timestamp: '2020-02-23 02:15:00.000',
    uuid: 'uuid1',
}

const person: Person = {
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
        queueMessages: jest.fn(() => Promise.resolve()) as any,
    }

    beforeEach(() => {
        jest.mocked(mockProducer.queueMessages).mockResolvedValue(Promise.resolve())

        hub = {
            kafkaProducer: mockProducer,
            teamManager: {
                fetchTeam: jest.fn(() => {}),
            },
            db: {
                kafkaProducer: mockProducer,
                fetchPerson: jest.fn(),
            },
            eventsToDropByToken: createEventsToDropByToken('drop_token:drop_id,drop_token_all:*'),
        }
        runner = new TestEventPipelineRunner(hub, pluginEvent, new EventsProcessor(hub))

        jest.mocked(populateTeamDataStep).mockResolvedValue({ result: pluginEvent })
        jest.mocked(pluginsProcessEventStep).mockResolvedValue({ result: pluginEvent })
        jest.mocked(processPersonsStep).mockResolvedValue({
            result: {
                event: pluginEvent,
                person: person,
            },
        })
        jest.mocked(prepareEventStep).mockResolvedValue({ result: preIngestionEvent })
        jest.mocked(createEventStep).mockResolvedValue({ result: createdEvent })
        jest.mocked(emitEventStep).mockResolvedValue({ result: null })
    })

    describe('runEventPipeline()', () => {
        it('runs steps starting from populateTeamDataStep', async () => {
            await runner.runEventPipeline(pipelineEvent)

            expect(runner.steps).toEqual([
                'populateTeamDataStep',
                'pluginsProcessEventStep',
                'normalizeEventStep',
                'processPersonsStep',
                'prepareEventStep',
                'extractHeatmapDataStep',
                'createEventStep',
                'emitEventStep',
            ])
            expect(runner.stepsWithArgs).toMatchSnapshot()
        })

        it('drops disallowed events', async () => {
            const event = {
                ...pipelineEvent,
                token: 'drop_token',
                distinct_id: 'drop_id',
            }
            await runner.runEventPipeline(event)
            expect(runner.steps).toEqual([])
        })

        it('does not drop disallowed token mismatching distinct_id events', async () => {
            const event = {
                ...pipelineEvent,
                token: 'drop_token',
            }
            await runner.runEventPipeline(event)
            expect(runner.steps).toEqual([
                'populateTeamDataStep',
                'pluginsProcessEventStep',
                'normalizeEventStep',
                'processPersonsStep',
                'prepareEventStep',
                'extractHeatmapDataStep',
                'createEventStep',
                'emitEventStep',
            ])
        })

        it('drops disallowed events by *', async () => {
            const event = {
                ...pipelineEvent,
                token: 'drop_token_all',
            }
            await runner.runEventPipeline(event)
            expect(runner.steps).toEqual([])
        })

        it('emits metrics for every step', async () => {
            const pipelineLastStepCounterSpy = jest.spyOn(metrics.pipelineLastStepCounter, 'labels')
            const eventProcessedAndIngestedCounterSpy = jest.spyOn(metrics.eventProcessedAndIngestedCounter, 'inc')
            const pipelineStepMsSummarySpy = jest.spyOn(metrics.pipelineStepMsSummary, 'labels')
            const pipelineStepErrorCounterSpy = jest.spyOn(metrics.pipelineStepErrorCounter, 'labels')

            const result = await runner.runEventPipeline(pipelineEvent)
            expect(result.error).toBeUndefined()

            expect(pipelineStepMsSummarySpy).toHaveBeenCalledTimes(8)
            expect(pipelineLastStepCounterSpy).toHaveBeenCalledTimes(1)
            expect(eventProcessedAndIngestedCounterSpy).toHaveBeenCalledTimes(1)
            expect(pipelineStepMsSummarySpy).toHaveBeenCalledWith('emitEventStep')
            expect(pipelineLastStepCounterSpy).toHaveBeenCalledWith('emitEventStep')
            expect(pipelineStepErrorCounterSpy).not.toHaveBeenCalled()
        })

        describe('early exits from pipeline', () => {
            beforeEach(() => {
                jest.mocked(pluginsProcessEventStep).mockResolvedValue({ result: null })
            })

            it('stops processing after step', async () => {
                await runner.runEventPipeline(pipelineEvent)

                expect(runner.steps).toEqual(['populateTeamDataStep', 'pluginsProcessEventStep'])
            })

            it('reports metrics and last step correctly', async () => {
                const pipelineLastStepCounterSpy = jest.spyOn(metrics.pipelineLastStepCounter, 'labels')
                const pipelineStepMsSummarySpy = jest.spyOn(metrics.pipelineStepMsSummary, 'labels')
                const pipelineStepErrorCounterSpy = jest.spyOn(metrics.pipelineStepErrorCounter, 'labels')

                await runner.runEventPipeline(pipelineEvent)

                expect(pipelineStepMsSummarySpy).toHaveBeenCalledTimes(2)
                expect(pipelineLastStepCounterSpy).toHaveBeenCalledWith('pluginsProcessEventStep')
                expect(pipelineStepErrorCounterSpy).not.toHaveBeenCalled()
            })
        })

        describe('errors during processing', () => {
            const error = new Error('testError')

            it('runs and increments metrics', async () => {
                const pipelineStepMsSummarySpy = jest.spyOn(metrics.pipelineStepMsSummary, 'labels')
                const pipelineLastStepCounterSpy = jest.spyOn(metrics.pipelineLastStepCounter, 'labels')
                const pipelineStepErrorCounterSpy = jest.spyOn(metrics.pipelineStepErrorCounter, 'labels')

                jest.mocked(prepareEventStep).mockRejectedValue(error)

                await runner.runEventPipeline(pipelineEvent)

                expect(pipelineStepMsSummarySpy).toHaveBeenCalledWith('populateTeamDataStep')
                expect(pipelineStepMsSummarySpy).toHaveBeenCalledWith('pluginsProcessEventStep')
                expect(pipelineStepMsSummarySpy).not.toHaveBeenCalledWith('prepareEventStep')
                expect(pipelineLastStepCounterSpy).not.toHaveBeenCalled()
                expect(pipelineStepErrorCounterSpy).toHaveBeenCalledWith('prepareEventStep')
            })

            it('emits failures to dead letter queue until createEvent', async () => {
                const pipelineStepDLQCounterSpy = jest.spyOn(metrics.pipelineStepDLQCounter, 'labels')
                jest.mocked(prepareEventStep).mockRejectedValue(error)

                await runner.runEventPipeline(pipelineEvent)

                expect(mockProducer.queueMessages).toHaveBeenCalledTimes(1)
                expect(JSON.parse(mockProducer.queueMessages.mock.calls[0][0].messages[0].value)).toMatchObject({
                    team_id: 2,
                    distinct_id: 'my_id',
                    error: 'Event ingestion failed. Error: testError',
                    error_location: 'plugin_server_ingest_event:prepareEventStep',
                })
                expect(pipelineStepDLQCounterSpy).toHaveBeenCalledWith('prepareEventStep')
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

                jest.mocked(populateTeamDataStep).mockResolvedValue({ result: event })

                await runner.runEventPipeline(event)
                expect(runner.steps).toEqual(['populateTeamDataStep'])
                expect(mockProducer.queueMessages).toHaveBeenCalledTimes(1)
                expect(JSON.parse(mockProducer.queueMessages.mock.calls[0][0].messages[0].value)).toMatchObject({
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
            let heatmapEvent: PipelineEvent
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
                }

                // setup just enough mocks that the right pipeline runs

                runner = new TestEventPipelineRunner(hub, heatmapEvent, new EventsProcessor(hub))

                jest.mocked(populateTeamDataStep).mockResolvedValue({ result: heatmapEvent as any })

                const heatmapPreIngestionEvent = {
                    ...preIngestionEvent,
                    event: '$$heatmap',
                    properties: {
                        ...heatmapEvent.properties,
                    },
                }
                jest.mocked(prepareEventStep).mockResolvedValue({ result: heatmapPreIngestionEvent })
            })

            it('runs the expected steps for heatmap_data', async () => {
                await runner.runEventPipeline(heatmapEvent)

                expect(runner.steps).toEqual([
                    'populateTeamDataStep',
                    'normalizeEventStep',
                    'prepareEventStep',
                    'extractHeatmapDataStep',
                ])
            })
        })

        describe('$exception events', () => {
            let exceptionEvent: PipelineEvent
            beforeEach(() => {
                exceptionEvent = {
                    ...pipelineEvent,
                    event: '$exception',
                    properties: {
                        ...pipelineEvent.properties,
                        $heatmap_data: {
                            url1: ['data'],
                            url2: ['more data'],
                        },
                    },
                }

                // setup just enough mocks that the right pipeline runs

                runner = new TestEventPipelineRunner(hub, exceptionEvent, new EventsProcessor(hub))

                jest.mocked(populateTeamDataStep).mockResolvedValue({ result: exceptionEvent as any })

                const result = {
                    ...preIngestionEvent,
                    event: '$exception',
                    properties: {
                        ...exceptionEvent.properties,
                    },
                }
                jest.mocked(prepareEventStep).mockResolvedValue({ result })
            })

            it('runs the expected steps for heatmap_data', async () => {
                await runner.runEventPipeline(exceptionEvent)

                expect(runner.steps).toEqual([
                    'populateTeamDataStep',
                    'pluginsProcessEventStep',
                    'normalizeEventStep',
                    'processPersonsStep',
                    'prepareEventStep',
                    'extractHeatmapDataStep',
                    'createEventStep',
                    'produceExceptionSymbolificationEventStep',
                ])
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
                jest.mocked(populateTeamDataStep).mockResolvedValue({ result: event })

                await runner.runEventPipeline(event)
                expect(runner.steps).toEqual(['populateTeamDataStep'])
                expect(mockProducer.queueMessages).toHaveBeenCalledTimes(1)
                expect(JSON.parse(mockProducer.queueMessages.mock.calls[0][0].messages[0].value)).toMatchObject({
                    team_id: 9,
                    type: 'invalid_event_when_process_person_profile_is_false',
                    details: JSON.stringify({ eventUuid: 'uuid1', event: eventName, distinctId: 'my_id' }),
                })
            }
        )
    })
})
