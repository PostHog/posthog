import { PluginEvent, ProcessedPluginEvent } from '@posthog/plugin-scaffold'
import * as Sentry from '@sentry/node'

import { runInSpan } from '../../../sentry'
import { Hub, PipelineEvent, PostIngestionEvent, PreIngestionEvent } from '../../../types'
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

    // KLUDGE: This is a temporary entry point for the pipeline while we transition away from
    // hitting Postgres in the capture endpoint. Eventually the entire pipeline should
    // follow this route and we can rename it to just be `runEventPipeline`.
    async runLightweightCaptureEndpointEventPipeline(
        event: PipelineEvent
    ): Promise<PreIngestionEvent | null | undefined> {
        this.hub.statsd?.increment('kafka_queue.lightweight_capture_endpoint_event_pipeline.start', {
            pipeline: 'lightweight_capture',
        })

        let result: PreIngestionEvent | null = null

        const eventWithTeam = await this.runStep(populateTeamDataStep, this, event)
        if (eventWithTeam != null) {
            result = await this.runEventPipelineSteps(eventWithTeam)
        } else {
            this.hub.statsd?.increment('kafka_queue.event_pipeline.step.last', {
                step: 'populateTeamDataStep',
            })
        }

        this.hub.statsd?.increment('kafka_queue.single_event.processed_and_ingested')

        return result
    }

    async runEventPipeline(event: PluginEvent): Promise<PostIngestionEvent | null> {
        this.hub.statsd?.increment('kafka_queue.event_pipeline.start', { pipeline: 'event' })
        const result = await this.runEventPipelineSteps(event)
        this.hub.statsd?.increment('kafka_queue.single_event.processed_and_ingested')
        return result
    }

    async runEventPipelineSteps(event: PluginEvent): Promise<PostIngestionEvent | null> {
        const bufferResult = await this.runStep(emitToBufferStep, this, event)
        if (bufferResult != null) {
            const [bufferResultEvent, personContainer] = bufferResult
            return this.runBufferEventPipelineSteps(bufferResultEvent, personContainer)
        } else {
            this.hub.statsd?.increment('kafka_queue.event_pipeline.step.last', {
                step: 'emitToBufferStep',
                team_id: event.team_id.toString(),
            })
        }

        return null
    }

    async runBufferEventPipeline(event: PluginEvent): Promise<PreIngestionEvent | null> {
        this.hub.statsd?.increment('kafka_queue.event_pipeline.start', { pipeline: 'buffer' })
        await this.runBufferEventPipelineSteps(
            event,
            new LazyPersonContainer(event.team_id, event.distinct_id, this.hub)
        )
        return null
    }

    async runBufferEventPipelineSteps(
        event: PluginEvent,
        personContainer: LazyPersonContainer
    ): Promise<PreIngestionEvent | null> {
        const didPersonExistAtStart = !!(await personContainer.get())

        const processedEvent = await this.runStep(pluginsProcessEventStep, this, event)

        if (processedEvent != null) {
            const processPersonsResult = await this.runStep(processPersonsStep, this, processedEvent, personContainer)

            if (processPersonsResult != null) {
                const [normalizedEvent, newPersonContainer] = processPersonsResult

                const preparedEvent = await this.runStep(prepareEventStep, this, normalizedEvent)
                if (preparedEvent != null) {
                    const result = await this.runStep(createEventStep, this, preparedEvent, newPersonContainer)
                    this.hub.statsd?.increment('kafka_queue.event_pipeline.step.last', {
                        step: 'createEventStep',
                        team_id: event.team_id.toString(),
                    })
                    return result
                } else {
                    this.hub.statsd?.increment('kafka_queue.event_pipeline.step.last', {
                        step: 'prepareEventStep',
                        team_id: event.team_id.toString(),
                    })
                }
            } else {
                this.hub.statsd?.increment('kafka_queue.event_pipeline.step.last', {
                    step: 'processPersonsStep',
                    team_id: event.team_id.toString(),
                })
            }
        } else {
            this.hub.statsd?.increment('kafka_queue.event_pipeline.step.last', {
                step: 'pluginsProcessEventStep',
                team_id: event.team_id.toString(),
            })
        }
        this.hub.statsd?.increment('kafka_queue.buffer_event.processed_and_ingested', {
            didPersonExistAtStart: String(!!didPersonExistAtStart),
        })
        return null
    }

    async runAsyncHandlersEventPipeline(event: PostIngestionEvent) {
        this.hub.statsd?.increment('kafka_queue.event_pipeline.start', { pipeline: 'asyncHandlers' })
        const personContainer = new LazyPersonContainer(event.teamId, event.distinctId, this.hub)
        const result = await this.runStep(runAsyncHandlersStep, this, event, personContainer)
        this.hub.statsd?.increment('kafka_queue.async_handlers.processed')
        return result
    }

    protected runStep<Step extends (...args: any[]) => any>(
        step: Step,
        ...args: Parameters<Step>
    ): ReturnType<Step> | null {
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
                    await this.handleError(err, step.name, args)
                    return null
                } finally {
                    clearTimeout(timeout)
                }
            }
        )
    }

    private async handleError(err: any, currentStepName: string, currentArgs: any) {
        const serializedArgs = currentArgs.map((arg: any) => this.serialize(arg))
        status.error('🔔', err)
        Sentry.captureException(err, { extra: { currentStepName, serializedArgs, originalEvent: this.originalEvent } })
        this.hub.statsd?.increment('kafka_queue.event_pipeline.step.error', { step: currentStepName })

        if (err instanceof DependencyUnavailableError) {
            // If this is an error with a dependency that we control, we want to
            // ensure that the caller knows that the event was not processed,
            // for a reason that we control and that is transient.
            throw err
        }

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

    private serialize(arg: any) {
        if (arg instanceof LazyPersonContainer) {
            // :KLUDGE: cloneObject fails with hub if we don't do this
            return { teamId: arg.teamId, distinctId: arg.distinctId, loaded: arg.loaded }
        }
        return arg
    }
}
