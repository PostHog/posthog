import { PluginEvent } from '@posthog/plugin-scaffold'

import { PreIngestionEvent } from '../../../../src/types'
import { createEventStep } from '../../../../src/worker/ingestion/event-pipeline/createEventStep'
import { emitToBufferStep } from '../../../../src/worker/ingestion/event-pipeline/emitToBufferStep'
import { pluginsProcessEventStep } from '../../../../src/worker/ingestion/event-pipeline/pluginsProcessEventStep'
import { prepareEventStep } from '../../../../src/worker/ingestion/event-pipeline/prepareEventStep'
import { runAsyncHandlersStep } from '../../../../src/worker/ingestion/event-pipeline/runAsyncHandlersStep'
import {
    EventPipelineRunner,
    EventPipelineStepsType,
    StepParameters,
    StepResult,
    StepType,
} from '../../../../src/worker/ingestion/event-pipeline/runner'
import { generateEventDeadLetterQueueMessage } from '../../../../src/worker/ingestion/utils'

jest.mock('../../../../src/utils/status')
jest.mock('../../../../src/worker/ingestion/event-pipeline/createEventStep')
jest.mock('../../../../src/worker/ingestion/event-pipeline/emitToBufferStep')
jest.mock('../../../../src/worker/ingestion/event-pipeline/pluginsProcessEventStep')
jest.mock('../../../../src/worker/ingestion/event-pipeline/prepareEventStep')
jest.mock('../../../../src/worker/ingestion/event-pipeline/runAsyncHandlersStep')
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

        jest.mocked(pluginsProcessEventStep).mockResolvedValue(['prepareEventStep', [pluginEvent]])
        jest.mocked(prepareEventStep).mockResolvedValue(['emitToBufferStep', [preIngestionEvent]])
        jest.mocked(emitToBufferStep).mockResolvedValue(['createEventStep', [preIngestionEvent]])
        jest.mocked(createEventStep).mockResolvedValue(['runAsyncHandlersStep', [preIngestionEvent]])
        jest.mocked(runAsyncHandlersStep).mockResolvedValue(null)
    })

    describe('runEventPipeline()', () => {
        it('runs all steps', async () => {
            await runner.runEventPipeline(pluginEvent)

            expect(runner.steps).toEqual([
                'pluginsProcessEventStep',
                'prepareEventStep',
                'emitToBufferStep',
                'createEventStep',
                'runAsyncHandlersStep',
            ])
            expect(runner.stepsWithArgs).toMatchSnapshot()
        })

        it('emits metrics for every step', async () => {
            await runner.runEventPipeline(pluginEvent)

            expect(hub.statsd.timing).toHaveBeenCalledTimes(5)
            expect(hub.statsd.increment).toBeCalledTimes(7)

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
                jest.mocked(prepareEventStep).mockResolvedValue(null)
            })

            it('stops processing after step', async () => {
                await runner.runEventPipeline(pluginEvent)

                expect(runner.steps).toEqual(['pluginsProcessEventStep', 'prepareEventStep'])
            })

            it('reports metrics and last step correctly', async () => {
                await runner.runEventPipeline(pluginEvent)

                expect(hub.statsd.timing).toHaveBeenCalledTimes(2)
                expect(hub.statsd.increment).toHaveBeenCalledWith('kafka_queue.event_pipeline.step.last', {
                    step: 'prepareEventStep',
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
            await runner.runBufferEventPipeline(preIngestionEvent)

            expect(runner.steps).toEqual(['createEventStep', 'runAsyncHandlersStep'])
            expect(runner.stepsWithArgs).toMatchSnapshot()
        })
    })
})
