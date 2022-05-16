import { PluginEvent } from '@posthog/plugin-scaffold'
import * as Sentry from '@sentry/node'

import { Hub, PreIngestionEvent } from '../../../types'
import { status } from '../../../utils/status'
import { generateEventDeadLetterQueueMessage } from '../utils'
import { createEventStep } from './createEventStep'
import { determineShouldBufferStep } from './determineShouldBufferStep'
import { pluginsProcessEventStep } from './pluginsProcessEventStep'
import { prepareEventStep } from './prepareEventStep'
import { runAsyncHandlersStep } from './runAsyncHandlersStep'

type StepParameters<T extends (...args: any[]) => any> = T extends (
    runner: EventPipelineRunner,
    ...args: infer P
) => any
    ? P
    : never

const EVENT_PIPELINE_STEPS = {
    pluginsProcessEventStep,
    prepareEventStep,
    determineShouldBufferStep,
    createEventStep,
    runAsyncHandlersStep,
}

type EventPipelineStepsType = typeof EVENT_PIPELINE_STEPS
type StepType = keyof EventPipelineStepsType
type NextStep<Step extends StepType> = [StepType, StepParameters<EventPipelineStepsType[Step]>]

export type StepResult =
    | null
    | NextStep<'pluginsProcessEventStep'>
    | NextStep<'prepareEventStep'>
    | NextStep<'determineShouldBufferStep'>
    | NextStep<'createEventStep'>
    | NextStep<'runAsyncHandlersStep'>

const STEPS_TO_EMIT_TO_DLQ_ON_FAILURE: Array<StepType> = [
    'pluginsProcessEventStep',
    'prepareEventStep',
    'determineShouldBufferStep',
    'createEventStep',
]

export class EventPipelineRunner {
    hub: Hub
    originalEvent: PluginEvent | undefined

    constructor(hub: Hub, originalEvent?: PluginEvent) {
        this.hub = hub
        this.originalEvent = originalEvent
    }

    async runMainPipeline(event: PluginEvent): Promise<void> {
        await this.runStep('prepareEventStep', event)
        this.hub.statsd?.increment('kafka_queue.single_event.processed_and_ingested')
    }

    async runBufferPipeline(event: PreIngestionEvent): Promise<void> {
        const person = await this.hub.db.fetchPerson(event.teamId, event.distinctId)
        await this.runStep('createEventStep', event, person)
        this.hub.statsd?.increment('kafka_queue.buffer_envent.processed_and_ingested')
    }

    async runStep<Step extends StepType, ArgsType extends StepParameters<EventPipelineStepsType[Step]>>(
        name: Step,
        ...args: ArgsType
    ): Promise<void> {
        let currentStepName: StepType = name
        let currentArgs: any = args

        while (true) {
            const timer = new Date()
            try {
                // eslint-disable-next-line @typescript-eslint/ban-ts-comment
                // @ts-ignore
                const stepResult = await EVENT_PIPELINE_STEPS[currentStepName](this, ...currentArgs)

                this.hub.statsd?.increment('kafka_queue.event_pipeline.step', { step: currentStepName })
                this.hub.statsd?.timing('kafka_queue.event_pipeline.step.timing', timer, { step: currentStepName })

                if (stepResult) {
                    ;[currentStepName, currentArgs] = stepResult
                } else {
                    this.hub.statsd?.increment('kafka_queue.event_pipeline.step.dropped', {
                        step: currentStepName,
                        team_id: String(this.originalEvent?.team_id),
                    })
                    break
                }
            } catch (err) {
                await this.handleError(err, currentStepName, currentArgs)
                break
            }
        }
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

        if (this.originalEvent && STEPS_TO_EMIT_TO_DLQ_ON_FAILURE.includes(currentStepName)) {
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
