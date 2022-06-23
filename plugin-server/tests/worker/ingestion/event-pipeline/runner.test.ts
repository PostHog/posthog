import { PluginEvent } from '@posthog/plugin-scaffold'
import { DateTime } from 'luxon'

import { Person, PreIngestionEvent } from '../../../../src/types'
import { emitToBufferStep } from '../../../../src/worker/ingestion/event-pipeline/1-emitToBufferStep'
import { pluginsProcessEventStep } from '../../../../src/worker/ingestion/event-pipeline/2-pluginsProcessEventStep'
import { processPersonsStep } from '../../../../src/worker/ingestion/event-pipeline/3-processPersonsStep'
import { prepareEventStep } from '../../../../src/worker/ingestion/event-pipeline/4-prepareEventStep'
import { createEventStep } from '../../../../src/worker/ingestion/event-pipeline/5-createEventStep'
import { runAsyncHandlersStep } from '../../../../src/worker/ingestion/event-pipeline/6-runAsyncHandlersStep'
import {
    EventPipelineRunner,
    EventPipelineStepsType,
    StepParameters,
    StepResult,
    StepType,
} from '../../../../src/worker/ingestion/event-pipeline/runner'
import { generateEventDeadLetterQueueMessage } from '../../../../src/worker/ingestion/utils'

jest.mock('../../../../src/utils/status')
jest.mock('../../../../src/worker/ingestion/event-pipeline/1-emitToBufferStep')
jest.mock('../../../../src/worker/ingestion/event-pipeline/2-pluginsProcessEventStep')
jest.mock('../../../../src/worker/ingestion/event-pipeline/3-processPersonsStep')
jest.mock('../../../../src/worker/ingestion/event-pipeline/4-prepareEventStep')
jest.mock('../../../../src/worker/ingestion/event-pipeline/5-createEventStep')
jest.mock('../../../../src/worker/ingestion/event-pipeline/6-runAsyncHandlersStep')
jest.mock('../../../../src/worker/ingestion/utils')

class TestEventPipelineRunner extends EventPipelineRunner {
    steps: Array<string> = []
    stepsWithArgs: Array<[string, any[]]> = []

    protected runStep<Step extends StepType, ArgsType extends StepParameters<EventPipelineStepsType[Step]>>(
        name: Step,
        ...args: ArgsType
    ): Promise<StepResult> {
        this.steps.push(name)
        this.stepsWithArgs.push([name, args])
        return super.runStep(name, ...args)
    }
}

const pluginEvent: PluginEvent = {
    distinct_id: 'my_id',
    ip: '127.0.0.1',
    site_url: 'http://localhost',
    team_id: 2,
    now: '2020-02-23T02:15:00Z',
    timestamp: '2020-02-23T02:15:00Z',
    event: 'default event',
    properties: {},
    uuid: 'uuid1',
}

const preIngestionEvent: PreIngestionEvent = {
    eventUuid: 'uuid1',
    distinctId: 'my_id',
    ip: '127.0.0.1',
    teamId: 2,
    timestamp: '2020-02-23T02:15:00Z',
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
        runner = new TestEventPipelineRunner(hub, pluginEvent)

        jest.mocked(emitToBufferStep).mockResolvedValue(['pluginsProcessEventStep', [pluginEvent, person]])
        jest.mocked(pluginsProcessEventStep).mockResolvedValue([
            'processPersonsStep',
            [pluginEvent, { person, personUpdateProperties: {} }],
        ])
        jest.mocked(processPersonsStep).mockResolvedValue([
            'prepareEventStep',
            [pluginEvent, { person, personUpdateProperties: {} }],
        ])
        jest.mocked(prepareEventStep).mockResolvedValue(['createEventStep', [preIngestionEvent]])
        jest.mocked(createEventStep).mockResolvedValue(['runAsyncHandlersStep', [preIngestionEvent]])
        jest.mocked(runAsyncHandlersStep).mockResolvedValue(null)
    })

    describe('runEventPipeline()', () => {
        it('runs all steps', async () => {
            await runner.runEventPipeline(pluginEvent)

            expect(runner.steps).toEqual([
                'emitToBufferStep',
                'pluginsProcessEventStep',
                'processPersonsStep',
                'prepareEventStep',
                'createEventStep',
                'runAsyncHandlersStep',
            ])
            expect(runner.stepsWithArgs).toMatchSnapshot()
        })

        it('emits metrics for every step', async () => {
            await runner.runEventPipeline(pluginEvent)

            expect(hub.statsd.timing).toHaveBeenCalledTimes(6)
            expect(hub.statsd.increment).toBeCalledTimes(9)

            expect(hub.statsd.increment).toHaveBeenCalledWith('kafka_queue.event_pipeline.step', {
                step: 'createEventStep',
            })
            expect(hub.statsd.increment).toHaveBeenCalledWith('kafka_queue.event_pipeline.step.last', {
                step: 'runAsyncHandlersStep',
                team_id: '2',
            })
            expect(hub.statsd.increment).not.toHaveBeenCalledWith('kafka_queue.event_pipeline.step.error')
        })

        describe('early exits from pipeline', () => {
            beforeEach(() => {
                jest.mocked(pluginsProcessEventStep).mockResolvedValue(null)
            })

            it('stops processing after step', async () => {
                await runner.runEventPipeline(pluginEvent)

                expect(runner.steps).toEqual(['emitToBufferStep', 'pluginsProcessEventStep'])
            })

            it('reports metrics and last step correctly', async () => {
                await runner.runEventPipeline(pluginEvent)

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

                await runner.runEventPipeline(pluginEvent)

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
                jest.mocked(generateEventDeadLetterQueueMessage).mockReturnValue('DLQ event' as any)
                jest.mocked(prepareEventStep).mockRejectedValue(error)

                await runner.runEventPipeline(pluginEvent)

                expect(hub.db.kafkaProducer.queueMessage).toHaveBeenCalledWith('DLQ event' as any)
                expect(hub.statsd.increment).toHaveBeenCalledWith('events_added_to_dead_letter_queue')
            })

            it('does not emit to dead letter queue for runAsyncHandlersStep', async () => {
                jest.mocked(runAsyncHandlersStep).mockRejectedValue(error)

                await runner.runEventPipeline(pluginEvent)

                expect(hub.db.kafkaProducer.queueMessage).not.toHaveBeenCalled()
                expect(hub.statsd.increment).not.toHaveBeenCalledWith('events_added_to_dead_letter_queue')
            })
        })
    })

    describe('runBufferEventPipeline()', () => {
        it('runs remaining steps', async () => {
            jest.mocked(hub.db.fetchPerson).mockResolvedValue('testPerson')

            await runner.runBufferEventPipeline(pluginEvent)

            expect(runner.steps).toEqual([
                'pluginsProcessEventStep',
                'processPersonsStep',
                'prepareEventStep',
                'createEventStep',
                'runAsyncHandlersStep',
            ])
            expect(runner.stepsWithArgs).toMatchSnapshot()
        })
    })

    describe('runAsyncHandlersEventPipeline()', () => {
        it('runs remaining steps', async () => {
            jest.mocked(hub.db.fetchPerson).mockResolvedValue('testPerson')

            await runner.runAsyncHandlersEventPipeline(preIngestionEvent)

            expect(runner.steps).toEqual(['runAsyncHandlersStep'])
            expect(runner.stepsWithArgs).toMatchSnapshot()
        })
    })
})
