import { PluginEvent, ProcessedPluginEvent } from '@posthog/plugin-scaffold'
import * as Sentry from '@sentry/node'
import { Counter } from 'prom-client'

import { eventDroppedCounter } from '../../../main/ingestion-queues/metrics'
import { runInSpan } from '../../../sentry'
import { Hub, PipelineEvent } from '../../../types'
import { DependencyUnavailableError } from '../../../utils/db/error'
import { timeoutGuard } from '../../../utils/db/utils'
import { stringToBoolean } from '../../../utils/env-utils'
import { status } from '../../../utils/status'
import { generateEventDeadLetterQueueMessage } from '../utils'
import { createEventStep } from './createEventStep'
import { pluginsProcessEventStep } from './pluginsProcessEventStep'
import { populateTeamDataStep } from './populateTeamDataStep'
import { prepareEventStep } from './prepareEventStep'
import { processPersonsStep } from './processPersonsStep'

export const silentFailuresAsyncHandlers = new Counter({
    name: 'async_handlers_silent_failure',
    help: 'Number silent failures from async handlers.',
})
const pipelineStepCompletionCounter = new Counter({
    name: 'events_pipeline_step_executed_total',
    help: 'Number of events that have completed the step',
    labelNames: ['step_name'],
})
const pipelineStepThrowCounter = new Counter({
    name: 'events_pipeline_step_throw_total',
    help: 'Number of events that have thrown error in the step',
    labelNames: ['step_name'],
})
const pipelineStepDLQCounter = new Counter({
    name: 'events_pipeline_step_dlq_total',
    help: 'Number of events that have been sent to DLQ in the step',
    labelNames: ['step_name'],
})

export type EventPipelineResult = {
    // Promises that the batch handler should await on before committing offsets,
    // contains the Kafka producer ACKs, to avoid blocking after every message.
    promises?: Array<Promise<void>>
    // Only used in tests
    // TODO: update to test for side-effects of running the pipeline rather than
    // this return type.
    lastStep: string
    args: any[]
    error?: string
}

class StepErrorNoRetry extends Error {
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
    private delayAcks: boolean
    private eventsToDropByToken: Map<string, string[]>

    constructor(hub: Hub, originalEvent: PipelineEvent | ProcessedPluginEvent, poEEmbraceJoin = false) {
        this.hub = hub
        this.originalEvent = originalEvent
        this.poEEmbraceJoin = poEEmbraceJoin

        // TODO: remove after successful rollout
        this.delayAcks = stringToBoolean(process.env.INGESTION_DELAY_WRITE_ACKS)

        this.eventsToDropByToken = new Map()
        process.env.DROP_EVENTS_BY_TOKEN_DISTINCT_ID?.split(',').forEach((pair) => {
            const [token, distinctID] = pair.split(':')
            this.eventsToDropByToken.set(token, [...(this.eventsToDropByToken.get(token) || []), distinctID])
        })
    }

    isEventBlacklisted(event: PipelineEvent): boolean {
        // During incidents we can use the the env DROP_EVENTS_BY_TOKEN_DISTINCT_ID
        // to drop events here before processing them which would allow us to catch up
        const key = event.token || event.team_id?.toString()
        if (!key) {
            return false // for safety don't drop events here, they are later dropped in teamDataPopulation
        }
        const dropIds = this.eventsToDropByToken.get(key)
        return dropIds?.includes(event.distinct_id) || dropIds?.includes('*') || false
    }

    async runEventPipeline(event: PipelineEvent): Promise<EventPipelineResult> {
        this.hub.statsd?.increment('kafka_queue.event_pipeline.start', { pipeline: 'event' })

        try {
            if (this.isEventBlacklisted(event)) {
                eventDroppedCounter
                    .labels({
                        event_type: 'analytics',
                        drop_cause: 'blacklisted',
                    })
                    .inc()
                return this.registerLastStep('eventBlacklistingStep', null, [event])
            }
            let result: EventPipelineResult
            const eventWithTeam = await this.runStep(populateTeamDataStep, [this, event], event.team_id || -1)
            if (eventWithTeam != null) {
                result = await this.runEventPipelineSteps(eventWithTeam)
            } else {
                result = this.registerLastStep('populateTeamDataStep', null, [event])
            }
            this.hub.statsd?.increment('kafka_queue.single_event.processed_and_ingested')
            return result
        } catch (error) {
            if (error instanceof StepErrorNoRetry) {
                // At the step level we have chosen to drop these events and send them to DLQ
                return { lastStep: error.step, args: [], error: error.message }
            } else {
                // Otherwise rethrow, which leads to Kafka offsets not getting committed and retries
                Sentry.captureException(error, {
                    tags: { pipeline_step: 'outside' },
                    extra: { originalEvent: this.originalEvent },
                })
                throw error
            }
        }
    }

    async runEventPipelineSteps(event: PluginEvent): Promise<EventPipelineResult> {
        if (
            process.env.POE_EMBRACE_JOIN_FOR_TEAMS === '*' ||
            process.env.POE_EMBRACE_JOIN_FOR_TEAMS?.split(',').includes(event.team_id.toString())
        ) {
            // https://docs.google.com/document/d/12Q1KcJ41TicIwySCfNJV5ZPKXWVtxT7pzpB3r9ivz_0
            // We're not using the buffer anymore
            // instead we'll (if within timeframe) merge into the newer personId

            // TODO: remove this step and runner env once we're confident that the new
            // ingestion pipeline is working well for all teams.
            this.poEEmbraceJoin = true
        }
        const processedEvent = await this.runStep(pluginsProcessEventStep, [this, event], event.team_id)

        if (processedEvent == null) {
            return this.registerLastStep('pluginsProcessEventStep', event.team_id, [event])
        }
        const [normalizedEvent, person] = await this.runStep(processPersonsStep, [this, processedEvent], event.team_id)

        const preparedEvent = await this.runStep(prepareEventStep, [this, normalizedEvent], event.team_id)

        const [rawClickhouseEvent, eventAck] = await this.runStep(
            createEventStep,
            [this, preparedEvent, person],
            event.team_id
        )
        if (this.delayAcks) {
            return this.registerLastStep('createEventStep', event.team_id, [rawClickhouseEvent, person], [eventAck])
        } else {
            await eventAck
            return this.registerLastStep('createEventStep', event.team_id, [rawClickhouseEvent, person])
        }
    }

    registerLastStep(
        stepName: string,
        teamId: number | null,
        args: any[],
        promises?: Array<Promise<void>>
    ): EventPipelineResult {
        this.hub.statsd?.increment('kafka_queue.event_pipeline.step.last', {
            step: stepName,
            team_id: String(teamId), // NOTE: potentially high cardinality
        })
        return { promises: promises, lastStep: stepName, args }
    }

    protected runStep<Step extends (...args: any[]) => any>(
        step: Step,
        args: Parameters<Step>,
        teamId: number,
        sentToDql = true
    ): ReturnType<Step> {
        const timer = new Date()

        return runInSpan(
            {
                op: 'runStep',
                description: step.name,
            },
            async () => {
                const timeout = timeoutGuard(
                    `Event pipeline step stalled. Timeout warning after 30 sec! step=${step.name} team_id=${teamId} distinct_id=${this.originalEvent.distinct_id}`,
                    {
                        step: step.name,
                        event: JSON.stringify(this.originalEvent),
                    }
                )
                try {
                    const result = await step(...args)
                    pipelineStepCompletionCounter.labels(step.name).inc()
                    this.hub.statsd?.increment('kafka_queue.event_pipeline.step', { step: step.name })
                    this.hub.statsd?.timing('kafka_queue.event_pipeline.step.timing', timer, { step: step.name })
                    return result
                } catch (err) {
                    await this.handleError(err, step.name, args, teamId, sentToDql)
                } finally {
                    clearTimeout(timeout)
                }
            }
        )
    }

    private shouldRetry(err: any): boolean {
        if (err instanceof DependencyUnavailableError) {
            // If this is an error with a dependency that we control, we want to
            // ensure that the caller knows that the event was not processed,
            // for a reason that we control and that is transient.
            return true
        }
        // TODO: Blacklist via env of errors we're going to put into DLQ instead of taking Kafka lag
        return false
    }

    private async handleError(err: any, currentStepName: string, currentArgs: any, teamId: number, sentToDql: boolean) {
        status.error('🔔', 'step_failed', { currentStepName, err })
        Sentry.captureException(err, {
            tags: { team_id: teamId, pipeline_step: currentStepName },
            extra: { currentArgs, originalEvent: this.originalEvent },
        })

        this.hub.statsd?.increment('kafka_queue.event_pipeline.step.error', { step: currentStepName })

        // Should we throw or should we drop and send the event to DLQ.
        if (this.shouldRetry(err)) {
            pipelineStepThrowCounter.labels(currentStepName).inc()
            throw err
        }

        if (sentToDql) {
            pipelineStepDLQCounter.labels(currentStepName).inc()
            try {
                const message = generateEventDeadLetterQueueMessage(
                    this.originalEvent,
                    err,
                    teamId,
                    `plugin_server_ingest_event:${currentStepName}`
                )
                await this.hub.db.kafkaProducer!.queueMessage(message)
                this.hub.statsd?.increment('events_added_to_dead_letter_queue')
            } catch (dlqError) {
                status.info('🔔', `Errored trying to add event to dead letter queue. Error: ${dlqError}`)
                Sentry.captureException(dlqError, {
                    tags: { team_id: teamId },
                    extra: { currentStepName, currentArgs, originalEvent: this.originalEvent, err },
                })
            }
        }

        // These errors are dropped rather than retried
        throw new StepErrorNoRetry(currentStepName, currentArgs, err.message)
    }
}
