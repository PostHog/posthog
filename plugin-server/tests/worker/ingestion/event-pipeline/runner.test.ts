import { PluginEvent } from '@posthog/plugin-scaffold'
import { DateTime } from 'luxon'

import { ISOTimestamp, Person, PipelineEvent, PreIngestionEvent } from '../../../../src/types'
import { createEventStep } from '../../../../src/worker/ingestion/event-pipeline/createEventStep'
import { pluginsProcessEventStep } from '../../../../src/worker/ingestion/event-pipeline/pluginsProcessEventStep'
import { populateTeamDataStep } from '../../../../src/worker/ingestion/event-pipeline/populateTeamDataStep'
import { prepareEventStep } from '../../../../src/worker/ingestion/event-pipeline/prepareEventStep'
import { processPersonsStep } from '../../../../src/worker/ingestion/event-pipeline/processPersonsStep'
import { processOnEventStep } from '../../../../src/worker/ingestion/event-pipeline/runAsyncHandlersStep'
import { EventPipelineRunner } from '../../../../src/worker/ingestion/event-pipeline/runner'

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
        this.stepsWithArgs.push([step.name, args])
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
            db: {
                kafkaProducer: { queueMessage: jest.fn() },
                fetchPerson: jest.fn(),
            },
            statsd: {
                increment: jest.fn(),
                timing: jest.fn(),
            },
        }
        process.env.DROP_EVENTS_BY_TOKEN_DISTINCT_ID = 'drop_token:drop_id,drop_token_all:*'
        runner = new TestEventPipelineRunner(hub, pluginEvent)

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
                'processPersonsStep',
                'prepareEventStep',
                'createEventStep',
            ])
            expect(runner.stepsWithArgs).toMatchSnapshot()
        })

        it('drops blacklisted events', async () => {
            const event = {
                ...pipelineEvent,
                token: 'drop_token',
                distinct_id: 'drop_id',
            }
            await runner.runEventPipeline(event)
            expect(runner.steps).toEqual([])
        })

        it('does not drop blacklisted token mismatching distinct_id events', async () => {
            const event = {
                ...pipelineEvent,
                token: 'drop_token',
            }
            await runner.runEventPipeline(event)
            expect(runner.steps).toEqual([
                'populateTeamDataStep',
                'pluginsProcessEventStep',
                'processPersonsStep',
                'prepareEventStep',
                'createEventStep',
            ])
        })

        it('drops blacklisted events by *', async () => {
            const event = {
                ...pipelineEvent,
                token: 'drop_token_all',
            }
            await runner.runEventPipeline(event)
            expect(runner.steps).toEqual([])
        })

        it('emits metrics for every step', async () => {
            const result = await runner.runEventPipeline(pipelineEvent)
            expect(result.error).toBeUndefined()

            expect(hub.statsd.timing).toHaveBeenCalledTimes(5)
            expect(hub.statsd.increment).toHaveBeenCalledTimes(8)

            expect(hub.statsd.increment).toHaveBeenCalledWith('kafka_queue.event_pipeline.step', {
                step: 'createEventStep',
            })
            expect(hub.statsd.increment).toHaveBeenCalledWith('kafka_queue.event_pipeline.step.last', {
                step: 'createEventStep',
                team_id: '2',
            })
            expect(hub.statsd.increment).not.toHaveBeenCalledWith('kafka_queue.event_pipeline.step.error')
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
                await runner.runEventPipeline(pipelineEvent)

                expect(hub.statsd.timing).toHaveBeenCalledTimes(2)
                expect(hub.statsd.increment).toHaveBeenCalledWith('kafka_queue.event_pipeline.step.last', {
                    step: 'pluginsProcessEventStep',
                    team_id: '2',
                })
                expect(hub.statsd.increment).not.toHaveBeenCalledWith('kafka_queue.event_pipeline.step.error')
            })
        })

        describe('errors during processing', () => {
            const error = new Error('testError')

            it('runs and increments metrics', async () => {
                jest.mocked(prepareEventStep).mockRejectedValue(error)

                await runner.runEventPipeline(pipelineEvent)

                expect(hub.statsd.increment).toHaveBeenCalledWith('kafka_queue.event_pipeline.step', {
                    step: 'populateTeamDataStep',
                })
                expect(hub.statsd.increment).toHaveBeenCalledWith('kafka_queue.event_pipeline.step', {
                    step: 'pluginsProcessEventStep',
                })
                expect(hub.statsd.increment).not.toHaveBeenCalledWith('kafka_queue.event_pipeline.step', {
                    step: 'prepareEventStep',
                })
                expect(hub.statsd.increment).not.toHaveBeenCalledWith('kafka_queue.event_pipeline.step.last')
                expect(hub.statsd.increment).toHaveBeenCalledWith('kafka_queue.event_pipeline.step.error', {
                    step: 'prepareEventStep',
                })
            })

            it('emits failures to dead letter queue until createEvent', async () => {
                jest.mocked(prepareEventStep).mockRejectedValue(error)

                await runner.runEventPipeline(pipelineEvent)

                expect(hub.db.kafkaProducer.queueMessage).toHaveBeenCalledTimes(1)
                expect(JSON.parse(hub.db.kafkaProducer.queueMessage.mock.calls[0][0].messages[0].value)).toMatchObject({
                    team_id: 2,
                    distinct_id: 'my_id',
                    error: 'ingestEvent failed. Error: testError',
                    error_location: 'plugin_server_ingest_event:prepareEventStep',
                })
                expect(hub.statsd.increment).toHaveBeenCalledWith('events_added_to_dead_letter_queue')
            })

            it('does not emit to dead letter queue for runAsyncHandlersStep', async () => {
                jest.mocked(processOnEventStep).mockRejectedValue(error)

                await runner.runEventPipeline(pipelineEvent)

                expect(hub.db.kafkaProducer.queueMessage).not.toHaveBeenCalled()
                expect(hub.statsd.increment).not.toHaveBeenCalledWith('events_added_to_dead_letter_queue')
            })
        })
    })
})
