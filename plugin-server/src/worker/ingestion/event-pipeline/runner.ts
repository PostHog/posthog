import { PluginEvent, ProcessedPluginEvent } from '@posthog/plugin-scaffold'
import * as Sentry from '@sentry/node'

import { runInSpan } from '../../../init'
import { Hub, IngestionEvent } from '../../../types'
import { timeoutGuard } from '../../../utils/db/utils'
import { status } from '../../../utils/status'
import { generateEventDeadLetterQueueMessage } from '../utils'
import { emitToBufferStep } from './1-emitToBufferStep'
import { pluginsProcessEventStep } from './2-pluginsProcessEventStep'
import { processPersonsStep } from './3-processPersonsStep'
import { prepareEventStep } from './4-prepareEventStep'
import { createEventStep } from './5-createEventStep'
import { runAsyncHandlersStep } from './6-runAsyncHandlersStep'

export type StepParameters<T extends (...args: any[]) => any> = T extends (
    runner: EventPipelineRunner,
    ...args: infer P
) => any
    ? P
    : never

const EVENT_PIPELINE_STEPS = {
    emitToBufferStep,
    pluginsProcessEventStep,
    processPersonsStep,
    prepareEventStep,
    createEventStep,
    runAsyncHandlersStep,
}

export type EventPipelineStepsType = typeof EVENT_PIPELINE_STEPS
export type StepType = keyof EventPipelineStepsType
export type NextStep<Step extends StepType> = [StepType, StepParameters<EventPipelineStepsType[Step]>]

export type StepResult =
    | null
    | NextStep<'emitToBufferStep'>
    | NextStep<'pluginsProcessEventStep'>
    | NextStep<'processPersonsStep'>
    | NextStep<'prepareEventStep'>
    | NextStep<'createEventStep'>
    | NextStep<'runAsyncHandlersStep'>

// Only used in tests
export type EventPipelineResult = {
    lastStep: StepType
    args: any[]
    error?: string
}

const STEPS_TO_EMIT_TO_DLQ_ON_FAILURE: Array<StepType> = [
    'emitToBufferStep',
    'pluginsProcessEventStep',
    'processPersonsStep',
    'prepareEventStep',
    'createEventStep',
]

export class EventPipelineRunner {
    hub: Hub
    originalEvent: PluginEvent | ProcessedPluginEvent

    constructor(hub: Hub, originalEvent: PluginEvent | ProcessedPluginEvent) {
        this.hub = hub
        this.originalEvent = originalEvent
    }

    async runEventPipeline(event: PluginEvent): Promise<EventPipelineResult> {
        this.hub.statsd?.increment('kafka_queue.event_pipeline.start', { pipeline: 'event' })
        const result = await this.runPipeline('emitToBufferStep', event)
        this.hub.statsd?.increment('kafka_queue.single_event.processed_and_ingested')
        return result
    }

    async runBufferEventPipeline(event: PluginEvent): Promise<EventPipelineResult> {
        this.hub.statsd?.increment('kafka_queue.event_pipeline.start', { pipeline: 'buffer' })
        const person = await this.hub.db.fetchPerson(event.team_id, event.distinct_id)
        const result = await this.runPipeline('pluginsProcessEventStep', event, person)
        this.hub.statsd?.increment('kafka_queue.buffer_event.processed_and_ingested', {
            didPersonExistAtStart: String(!person),
        })
        return result
    }

    async runAsyncHandlersEventPipeline(event: IngestionEvent): Promise<EventPipelineResult> {
        this.hub.statsd?.increment('kafka_queue.event_pipeline.start', { pipeline: 'asyncHandlers' })
        const person = await this.hub.db.fetchPerson(event.teamId, event.distinctId)
        const result = await this.runPipeline('runAsyncHandlersStep', { ...event, person })
        this.hub.statsd?.increment('kafka_queue.async_handlers.processed')
        return result
    }

    private async runPipeline<Step extends StepType, ArgsType extends StepParameters<EventPipelineStepsType[Step]>>(
        name: Step,
        ...args: ArgsType
    ): Promise<EventPipelineResult> {
        let currentStepName: StepType = name
        let currentArgs: any = args

        while (true) {
            const timer = new Date()
            try {
                const stepResult = await this.runStep(currentStepName, ...currentArgs)

                this.hub.statsd?.increment('kafka_queue.event_pipeline.step', { step: currentStepName })
                this.hub.statsd?.timing('kafka_queue.event_pipeline.step.timing', timer, { step: currentStepName })

                if (stepResult) {
                    ;[currentStepName, currentArgs] = stepResult
                } else {
                    this.hub.statsd?.increment('kafka_queue.event_pipeline.step.last', {
                        step: currentStepName,
                        team_id: String(this.originalEvent?.team_id),
                    })
                    return {
                        lastStep: currentStepName,
                        args: currentArgs,
                    }
                }
            } catch (error) {
                await this.handleError(error, currentStepName, currentArgs)
                return {
                    lastStep: currentStepName,
                    args: currentArgs,
                    error: error.message,
                }
            }
        }
    }

    protected runStep<Step extends StepType, ArgsType extends StepParameters<EventPipelineStepsType[Step]>>(
        name: Step,
        ...args: ArgsType
    ): Promise<StepResult> {
        return runInSpan(
            {
                op: 'runStep',
                description: name,
            },
            () => {
                const timeout = timeoutGuard('Event pipeline step stalled. Timeout warning after 30 sec!', {
                    step: name,
                    event: JSON.stringify(this.originalEvent),
                })
                try {
                    // eslint-disable-next-line @typescript-eslint/ban-ts-comment
                    // @ts-expect-error
                    return EVENT_PIPELINE_STEPS[name](this, ...args)
                } finally {
                    clearTimeout(timeout)
                }
            }
        )
    }

    nextStep<Step extends StepType, ArgsType extends StepParameters<EventPipelineStepsType[Step]>>(
        name: Step,
        ...args: ArgsType
    ): NextStep<Step> {
        return [name, args]
    }

    private async handleError(err: any, currentStepName: StepType, currentArgs: any) {
        status.info('🔔', err)
        Sentry.captureException(err, { extra: { currentStepName, currentArgs, originalEvent: this.originalEvent } })
        this.hub.statsd?.increment('kafka_queue.event_pipeline.step.error', { step: currentStepName })

        if (STEPS_TO_EMIT_TO_DLQ_ON_FAILURE.includes(currentStepName)) {
            try {
                const message = generateEventDeadLetterQueueMessage(this.originalEvent, err)
                await this.hub.db.kafkaProducer!.queueMessage(message)
                this.hub.statsd?.increment('events_added_to_dead_letter_queue')
            } catch (dlqError) {
                status.info('🔔', `Errored trying to add event to dead letter queue. Error: ${dlqError}`)
                Sentry.captureException(dlqError, {
                    extra: { currentStepName, currentArgs, originalEvent: this.originalEvent, err },
                })
            }
        }
    }
}
