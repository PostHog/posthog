import { PluginEvent, ProcessedPluginEvent } from '@posthog/plugin-scaffold'
import * as Sentry from '@sentry/node'

import { runInSpan } from '../../../sentry'
import { Hub, PipelineEvent, PostIngestionEvent } from '../../../types'
import { DependencyUnavailableError } from '../../../utils/db/error'
import { timeoutGuard } from '../../../utils/db/utils'
import { status } from '../../../utils/status'
import { LazyPersonContainer } from '../lazy-person-container'
import { generateEventDeadLetterQueueMessage } from '../utils'
import { createEventStep } from './createEventStep'
import { emitToBufferStep } from './emitToBufferStep'
import { pluginsProcessEventStep } from './pluginsProcessEventStep'
import { populateTeamDataStep } from './populateTeamDataStep'
import { prepareEventStep } from './prepareEventStep'
import { processPersonsStep } from './processPersonsStep'
import { runAsyncHandlersStep } from './runAsyncHandlersStep'

// Only used in tests
// TODO: update to test for side-effects of running the pipeline rather than
// this return type.
export type EventPipelineResult = {
    lastStep: string
    args: any[]
    error?: string
}

class StepError extends Error {
    step: string
    args: any[]
    constructor(step: string, args: any[], message: string) {
        super(message)
        this.step = step
        this.args = args
    }
}

export class EventPipelineRunner {
    hub: Hub
    originalEvent: PipelineEvent | ProcessedPluginEvent

    // See https://docs.google.com/document/d/12Q1KcJ41TicIwySCfNJV5ZPKXWVtxT7pzpB3r9ivz_0
    poEEmbraceJoin: boolean

    constructor(hub: Hub, originalEvent: PipelineEvent | ProcessedPluginEvent, poEEmbraceJoin = false) {
        this.hub = hub
        this.originalEvent = originalEvent
        this.poEEmbraceJoin = poEEmbraceJoin
    }

    async runEventPipeline(event: PipelineEvent): Promise<EventPipelineResult> {
        this.hub.statsd?.increment('kafka_queue.event_pipeline.start', { pipeline: 'event' })

        try {
            let result: EventPipelineResult | null = null
            const eventWithTeam = await this.runStep(populateTeamDataStep, [this, event])
            if (eventWithTeam != null) {
                result = await this.runEventPipelineSteps(eventWithTeam)
            } else {
                result = this.registerLastStep('populateTeamDataStep', null, [event])
            }

            this.hub.statsd?.increment('kafka_queue.single_event.processed_and_ingested')
            return result
        } catch (error) {
            if (error instanceof DependencyUnavailableError) {
                // If this is an error with a dependency that we control, we want to
                // ensure that the caller knows that the event was not processed,
                // for a reason that we control and that is transient.
                throw error
            }

            return { lastStep: error.step, args: [], error: error.message }
        }
    }

    async runEventPipelineSteps(event: PluginEvent): Promise<EventPipelineResult> {
        const bufferResult = await this.runStep(emitToBufferStep, [this, event])
        if (bufferResult != null) {
            const [bufferResultEvent, personContainer] = bufferResult
            return this.runBufferEventPipelineSteps(bufferResultEvent, personContainer)
        } else {
            return this.registerLastStep('emitToBufferStep', event.team_id, [event])
        }
    }

    async runBufferEventPipeline(event: PluginEvent): Promise<EventPipelineResult> {
        try {
            this.hub.statsd?.increment('kafka_queue.event_pipeline.start', { pipeline: 'buffer' })
            const personContainer = new LazyPersonContainer(event.team_id, event.distinct_id, this.hub)
            const didPersonExistAtStart = !!(await personContainer.get())
            const result = await this.runBufferEventPipelineSteps(event, personContainer)

            this.hub.statsd?.increment('kafka_queue.buffer_event.processed_and_ingested', {
                didPersonExistAtStart: String(!!didPersonExistAtStart),
            })
            return result
        } catch (error) {
            if (error instanceof DependencyUnavailableError) {
                // If this is an error with a dependency that we control, we want to
                // ensure that the caller knows that the event was not processed,
                // for a reason that we control and that is transient.
                throw error
            }

            return { lastStep: error.step, args: [], error: error.message }
        }
    }

    async runBufferEventPipelineSteps(
        event: PluginEvent,
        personContainer: LazyPersonContainer
    ): Promise<EventPipelineResult> {
        const processedEvent = await this.runStep(pluginsProcessEventStep, [this, event])

        if (processedEvent == null) {
            return this.registerLastStep('pluginsProcessEventStep', event.team_id, [event])
        }
        const [normalizedEvent, newPersonContainer] = await this.runStep(processPersonsStep, [
            this,
            processedEvent,
            personContainer,
        ])

        const preparedEvent = await this.runStep(prepareEventStep, [this, normalizedEvent])

        await this.runStep(createEventStep, [this, preparedEvent, newPersonContainer])
        return this.registerLastStep('createEventStep', event.team_id, [preparedEvent, newPersonContainer])
    }

    async runAsyncHandlersEventPipeline(event: PostIngestionEvent): Promise<EventPipelineResult> {
        try {
            this.hub.statsd?.increment('kafka_queue.event_pipeline.start', { pipeline: 'asyncHandlers' })
            const personContainer = new LazyPersonContainer(event.teamId, event.distinctId, this.hub)
            await this.runStep(runAsyncHandlersStep, [this, event, personContainer], false)
            this.hub.statsd?.increment('kafka_queue.async_handlers.processed')
            return this.registerLastStep('runAsyncHandlersStep', event.teamId, [event, personContainer])
        } catch (error) {
            if (error instanceof DependencyUnavailableError) {
                // If this is an error with a dependency that we control, we want to
                // ensure that the caller knows that the event was not processed,
                // for a reason that we control and that is transient.
                throw error
            }

            return { lastStep: error.step, args: [], error: error.message }
        }
    }

    registerLastStep(stepName: string, teamId: number | null, args: any[]): EventPipelineResult {
        this.hub.statsd?.increment('kafka_queue.event_pipeline.step.last', {
            step: stepName,
            team_id: String(teamId), // NOTE: potentially high cardinality
        })
        return { lastStep: stepName, args: args.map((arg) => this.serialize(arg)) }
    }

    protected runStep<Step extends (...args: any[]) => any>(
        step: Step,
        args: Parameters<Step>,
        sentToDql = true
    ): ReturnType<Step> {
        const timer = new Date()

        return runInSpan(
            {
                op: 'runStep',
                description: step.name,
            },
            async () => {
                const timeout = timeoutGuard('Event pipeline step stalled. Timeout warning after 30 sec!', {
                    step: step.name,
                    event: JSON.stringify(this.originalEvent),
                })
                try {
                    const result = await step(...args)
                    this.hub.statsd?.increment('kafka_queue.event_pipeline.step', { step: step.name })
                    this.hub.statsd?.timing('kafka_queue.event_pipeline.step.timing', timer, { step: step.name })
                    return result
                } catch (err) {
                    await this.handleError(err, step.name, args, sentToDql)
                } finally {
                    clearTimeout(timeout)
                }
            }
        )
    }

    private async handleError(err: any, currentStepName: string, currentArgs: any, sentToDql: boolean) {
        const serializedArgs = currentArgs.map((arg: any) => this.serialize(arg))
        status.error('🔔', 'step_failed', { currentStepName, err })
        Sentry.captureException(err, { extra: { currentStepName, serializedArgs, originalEvent: this.originalEvent } })
        this.hub.statsd?.increment('kafka_queue.event_pipeline.step.error', { step: currentStepName })

        if (err instanceof DependencyUnavailableError) {
            // If this is an error with a dependency that we control, we want to
            // ensure that the caller knows that the event was not processed,
            // for a reason that we control and that is transient.
            throw err
        }

        if (sentToDql) {
            try {
                const message = generateEventDeadLetterQueueMessage(this.originalEvent, err)
                await this.hub.db.kafkaProducer!.queueMessage(message)
                this.hub.statsd?.increment('events_added_to_dead_letter_queue')
            } catch (dlqError) {
                status.info('🔔', `Errored trying to add event to dead letter queue. Error: ${dlqError}`)
                Sentry.captureException(dlqError, {
                    extra: { currentStepName, serializedArgs, originalEvent: this.originalEvent, err },
                })
            }
        }

        throw new StepError(currentStepName, currentArgs, err.message)
    }

    private serialize(arg: any) {
        if (arg instanceof LazyPersonContainer) {
            // :KLUDGE: cloneObject fails with hub if we don't do this
            return { teamId: arg.teamId, distinctId: arg.distinctId, loaded: arg.loaded }
        }
        return arg
    }
}
