import { PluginEvent } from '@posthog/plugin-scaffold'
import { DateTime } from 'luxon'

import { ISOTimestamp, Person, PipelineEvent, PreIngestionEvent } from '../../../../src/types'
import { createEventsToDropByToken } from '../../../../src/utils/db/hub'
import { createEventStep } from '../../../../src/worker/ingestion/event-pipeline/createEventStep'
import * as metrics from '../../../../src/worker/ingestion/event-pipeline/metrics'
import { pluginsProcessEventStep } from '../../../../src/worker/ingestion/event-pipeline/pluginsProcessEventStep'
import { populateTeamDataStep } from '../../../../src/worker/ingestion/event-pipeline/populateTeamDataStep'
import { prepareEventStep } from '../../../../src/worker/ingestion/event-pipeline/prepareEventStep'
import { processPersonsStep } from '../../../../src/worker/ingestion/event-pipeline/processPersonsStep'
import { processOnEventStep } from '../../../../src/worker/ingestion/event-pipeline/runAsyncHandlersStep'
import { EventPipelineRunner } from '../../../../src/worker/ingestion/event-pipeline/runner'
import { EventsProcessor } from '../../../../src/worker/ingestion/process-event'

jest.mock('../../../../src/worker/ingestion/event-pipeline/populateTeamDataStep')
jest.mock('../../../../src/worker/ingestion/event-pipeline/pluginsProcessEventStep')
jest.mock('../../../../src/worker/ingestion/event-pipeline/processPersonsStep')
jest.mock('../../../../src/worker/ingestion/event-pipeline/prepareEventStep')
jest.mock('../../../../src/worker/ingestion/event-pipeline/createEventStep')
jest.mock('../../../../src/worker/ingestion/event-pipeline/runAsyncHandlersStep')

class TestEventPipelineRunner extends EventPipelineRunner {
    steps: Array<string> = []
    stepsWithArgs: Array<[string, any[]]> = []

    protected runStep(step: any, [runner, ...args]: any[], teamId: number, sendtoDLQ: boolean) {
        this.steps.push(step.name)

        // We stringify+parse to clone the `args` object, since we do a lot of event mutation
        // and pass the same object around by reference. We want to see a "snapshot" of the args
        // sent to each step, rather than the final mutated object (which many steps actually share
        // in practice, for better or worse).
        this.stepsWithArgs.push([step.name, JSON.parse(JSON.stringify(args))])

        return super.runStep(step, [runner, ...args], teamId, sendtoDLQ)
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
    timestamp: '2020-02-23T02:15:00.000Z' as ISOTimestamp,
    event: '$pageview',
    properties: {},
    elementsList: [],
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

    beforeEach(() => {
        hub = {
            kafkaProducer: { queueMessage: jest.fn() },
            teamManager: {
                fetchTeam: jest.fn(() => {}),
            },
            db: {
                kafkaProducer: { queueMessage: jest.fn() },
                fetchPerson: jest.fn(),
            },
            eventsToDropByToken: createEventsToDropByToken('drop_token:drop_id,drop_token_all:*'),
        }
        runner = new TestEventPipelineRunner(hub, pluginEvent, new EventsProcessor(hub))

        jest.mocked(populateTeamDataStep).mockResolvedValue(pluginEvent)
        jest.mocked(pluginsProcessEventStep).mockResolvedValue(pluginEvent)
        jest.mocked(processPersonsStep).mockResolvedValue([
            pluginEvent,
            { person, personUpdateProperties: {}, get: () => Promise.resolve(person) } as any,
        ])
        jest.mocked(prepareEventStep).mockResolvedValue(preIngestionEvent)
        jest.mocked(createEventStep).mockResolvedValue([null, Promise.resolve()])
        jest.mocked(processOnEventStep).mockResolvedValue(null)
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
                'enrichExceptionEventStep',
                'createEventStep',
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
                'enrichExceptionEventStep',
                'createEventStep',
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
            expect(pipelineStepMsSummarySpy).toHaveBeenCalledWith('createEventStep')
            expect(pipelineLastStepCounterSpy).toHaveBeenCalledWith('createEventStep')
            expect(pipelineStepErrorCounterSpy).not.toHaveBeenCalled()
        })

        describe('early exits from pipeline', () => {
            beforeEach(() => {
                jest.mocked(pluginsProcessEventStep).mockResolvedValue(null)
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

                expect(hub.db.kafkaProducer.queueMessage).toHaveBeenCalledTimes(1)
                expect(
                    JSON.parse(hub.db.kafkaProducer.queueMessage.mock.calls[0][0].kafkaMessage.messages[0].value)
                ).toMatchObject({
                    team_id: 2,
                    distinct_id: 'my_id',
                    error: 'Event ingestion failed. Error: testError',
                    error_location: 'plugin_server_ingest_event:prepareEventStep',
                })
                expect(pipelineStepDLQCounterSpy).toHaveBeenCalledWith('prepareEventStep')
            })

            it('does not emit to dead letter queue for runAsyncHandlersStep', async () => {
                const pipelineStepDLQCounterSpy = jest.spyOn(metrics.pipelineStepDLQCounter, 'labels')
                jest.mocked(processOnEventStep).mockRejectedValue(error)

                await runner.runEventPipeline(pipelineEvent)

                expect(hub.db.kafkaProducer.queueMessage).not.toHaveBeenCalled()
                expect(pipelineStepDLQCounterSpy).not.toHaveBeenCalled()
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

                const hub: any = {
                    db: {
                        kafkaProducer: { queueMessage: jest.fn() },
                    },
                }
                const runner = new TestEventPipelineRunner(hub, event, new EventsProcessor(hub))
                jest.mocked(populateTeamDataStep).mockResolvedValue(event)

                await runner.runEventPipeline(event)
                expect(runner.steps).toEqual(['populateTeamDataStep'])
                expect(hub.db.kafkaProducer.queueMessage).toHaveBeenCalledTimes(1)
                expect(
                    JSON.parse(hub.db.kafkaProducer.queueMessage.mock.calls[0][0].kafkaMessage.messages[0].value)
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

                jest.mocked(populateTeamDataStep).mockResolvedValue(heatmapEvent as any)

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
                await runner.runEventPipeline(heatmapEvent)

                expect(runner.steps).toEqual([
                    'populateTeamDataStep',
                    'normalizeEventStep',
                    'prepareEventStep',
                    'extractHeatmapDataStep',
                ])
            })
        })
    })
})

describe('EventPipelineRunner $process_person_profile=false', () => {
    it('drops events that are not allowed when $process_person_profile=false', async () => {
        for (const eventName of ['$identify', '$create_alias', '$merge_dangerously', '$groupidentify']) {
            const event = {
                ...pipelineEvent,
                properties: { $process_person_profile: false },
                event: eventName,
                team_id: 9,
            }

            const hub: any = {
                db: {
                    kafkaProducer: { queueMessage: jest.fn() },
                },
            }
            const runner = new TestEventPipelineRunner(hub, event, new EventsProcessor(hub))
            jest.mocked(populateTeamDataStep).mockResolvedValue(event)

            await runner.runEventPipeline(event)
            expect(runner.steps).toEqual(['populateTeamDataStep'])
            expect(hub.db.kafkaProducer.queueMessage).toHaveBeenCalledTimes(1)
            expect(
                JSON.parse(hub.db.kafkaProducer.queueMessage.mock.calls[0][0].kafkaMessage.messages[0].value)
            ).toMatchObject({
                team_id: 9,
                type: 'invalid_event_when_process_person_profile_is_false',
                details: JSON.stringify({ eventUuid: 'uuid1', event: eventName, distinctId: 'my_id' }),
            })
        }
    })
})
