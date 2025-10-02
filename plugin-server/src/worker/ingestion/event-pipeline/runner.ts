import { DateTime } from 'luxon'

import { PluginEvent } from '@posthog/plugin-scaffold'

import { HogTransformerService, TransformationResult } from '../../../cdp/hog-transformations/hog-transformer.service'
import { PipelineResult, dlq, drop, isOkResult, ok } from '../../../ingestion/pipelines/results'
import { EventHeaders, Hub, Person, PipelineEvent, PreIngestionEvent, RawKafkaEvent, Team } from '../../../types'
import { DependencyUnavailableError } from '../../../utils/db/error'
import { timeoutGuard } from '../../../utils/db/utils'
import { normalizeProcessPerson } from '../../../utils/event'
import { logger } from '../../../utils/logger'
import { captureException } from '../../../utils/posthog'
import { GroupStoreForBatch } from '../groups/group-store-for-batch.interface'
import { PersonMergeLimitExceededError } from '../persons/person-merge-types'
import { MergeMode, determineMergeMode } from '../persons/person-merge-types'
import { PersonsStoreForBatch } from '../persons/persons-store-for-batch'
import { EventsProcessor } from '../process-event'
import { captureIngestionWarning } from '../utils'
import { createEventStep } from './createEventStep'
import { dropOldEventsStep } from './dropOldEventsStep'
import { emitEventStep } from './emitEventStep'
import { extractHeatmapDataStep } from './extractHeatmapDataStep'
import {
    eventProcessedAndIngestedCounter,
    pipelineLastStepCounter,
    pipelineStepErrorCounter,
    pipelineStepMsSummary,
    pipelineStepStalledCounter,
    pipelineStepThrowCounter,
} from './metrics'
import { normalizeEventStep } from './normalizeEventStep'
import { prepareEventStep } from './prepareEventStep'
import { processPersonsStep } from './processPersonsStep'
import { transformEventStep } from './transformEventStep'

export type EventPipelineResult = {
    // Promises that the batch handler should await on before committing offsets,
    // contains the Kafka producer ACKs and message promises, to avoid blocking after every message.
    ackPromises?: Array<Promise<void>>
    // Only used in tests
    // TODO: update to test for side-effects of running the pipeline rather than
    // this return type.
    lastStep: string
    args: any[]
    error?: string
}

export type EventPipelinePipelineResult = PipelineResult<EventPipelineResult>

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
    originalEvent: PipelineEvent
    eventsProcessor: EventsProcessor
    hogTransformer: HogTransformerService | null
    personsStoreForBatch: PersonsStoreForBatch
    groupStoreForBatch: GroupStoreForBatch
    mergeMode: MergeMode
    headers?: EventHeaders

    constructor(
        hub: Hub,
        event: PipelineEvent,
        hogTransformer: HogTransformerService | null = null,
        personsStoreForBatch: PersonsStoreForBatch,
        groupStoreForBatch: GroupStoreForBatch,
        headers?: EventHeaders
    ) {
        this.hub = hub
        this.originalEvent = event
        this.eventsProcessor = new EventsProcessor(hub)
        this.hogTransformer = hogTransformer
        this.personsStoreForBatch = personsStoreForBatch
        this.groupStoreForBatch = groupStoreForBatch
        this.mergeMode = determineMergeMode(hub)
        this.headers = headers
    }

    /**
     * Heatmap ingestion will eventually be its own plugin server deployment
     * in the meantime we run this set of steps instead of wrapping each step in a conditional
     * in the main pipeline steps runner
     * or having a conditional inside each step
     * // TODO move this out into its own pipeline runner when splitting the deployment
     */
    async runHeatmapPipelineSteps(
        event: PluginEvent,
        kafkaAcks: Promise<void>[]
    ): Promise<EventPipelinePipelineResult> {
        const processPerson = false

        const normalizeResult = await this.runStep<[PluginEvent, DateTime], typeof normalizeEventStep>(
            normalizeEventStep,
            [event, processPerson],
            event.team_id
        )
        if (!isOkResult(normalizeResult)) {
            return normalizeResult
        }
        const [normalizedEvent] = normalizeResult.value

        const prepareResult = await this.runStep<PreIngestionEvent, typeof prepareEventStep>(
            prepareEventStep,
            [this, normalizedEvent, processPerson],
            event.team_id
        )
        if (!isOkResult(prepareResult)) {
            return prepareResult
        }
        const preparedEvent = prepareResult.value

        const extractResult = await this.runStep<[PreIngestionEvent, Promise<void>[]], typeof extractHeatmapDataStep>(
            extractHeatmapDataStep,
            [this, preparedEvent],
            event.team_id
        )
        if (!isOkResult(extractResult)) {
            return extractResult
        }
        const [preparedEventWithoutHeatmaps, heatmapKafkaAcks] = extractResult.value

        if (heatmapKafkaAcks.length > 0) {
            heatmapKafkaAcks.forEach((ack) => kafkaAcks.push(ack))
        }

        return ok(this.registerLastStep('extractHeatmapDataStep', [preparedEventWithoutHeatmaps], kafkaAcks))
    }

    async runEventPipeline(event: PipelineEvent, team: Team): Promise<EventPipelinePipelineResult> {
        this.originalEvent = event

        try {
            const pluginEvent: PluginEvent = {
                ...event,
                team_id: team.id,
            }

            const result = await this.runEventPipelineSteps(pluginEvent, team)

            // If the pipeline steps returned a non-OK result, return it directly
            if (!isOkResult(result)) {
                return result
            }

            eventProcessedAndIngestedCounter.inc()
            return result
        } catch (error) {
            if (error instanceof StepErrorNoRetry) {
                // At the step level we have chosen to drop these events and send them to DLQ
                return dlq('Step error - non-retriable', error)
            } else {
                // Otherwise rethrow, which leads to Kafka offsets not getting committed and retries
                captureException(error, {
                    tags: { pipeline_step: 'outside' },
                    extra: { originalEvent: this.originalEvent },
                })
                throw error
            }
        }
    }

    async runEventPipelineSteps(event: PluginEvent, team: Team): Promise<EventPipelinePipelineResult> {
        const kafkaAcks: Promise<void>[] = []

        let processPerson = true // The default.

        // Set either at capture time, or in the populateTeamData step, if team-level opt-out is enabled.
        if (event.properties && '$process_person_profile' in event.properties) {
            const propValue = event.properties.$process_person_profile
            if (propValue === true) {
                // This is the default, and `true` is one of the two valid values.
            } else if (propValue === false) {
                // Only a boolean `false` disables person processing.
                processPerson = false

                if (['$identify', '$create_alias', '$merge_dangerously', '$groupidentify'].includes(event.event)) {
                    kafkaAcks.push(
                        captureIngestionWarning(
                            this.hub.db.kafkaProducer,
                            event.team_id,
                            'invalid_event_when_process_person_profile_is_false',
                            {
                                eventUuid: event.uuid,
                                event: event.event,
                                distinctId: event.distinct_id,
                            },
                            { alwaysSend: true }
                        )
                    )

                    return drop('Invalid event for provided flags')
                }

                // If person processing is disabled, go ahead and remove person related keys before
                // any plugins have a chance to see them.
                event = normalizeProcessPerson(event, processPerson)
            } else {
                // Anything other than `true` or `false` is invalid, and the default (true) will be
                // used.
                kafkaAcks.push(
                    captureIngestionWarning(
                        this.hub.db.kafkaProducer,
                        event.team_id,
                        'invalid_process_person_profile',
                        {
                            eventUuid: event.uuid,
                            event: event.event,
                            distinctId: event.distinct_id,
                            $process_person_profile: propValue,
                            message: 'Only a boolean value is valid for the $process_person_profile property',
                        },
                        { alwaysSend: false }
                    )
                )
            }
        }

        if (event.event === '$$client_ingestion_warning') {
            await captureIngestionWarning(
                this.hub.db.kafkaProducer,
                event.team_id,
                'client_ingestion_warning',
                {
                    eventUuid: event.uuid,
                    event: event.event,
                    distinctId: event.distinct_id,
                    message: event.properties?.$$client_ingestion_warning_message,
                },
                { alwaysSend: true }
            )

            return drop('Client ingestion warning event')
        }

        if (event.event === '$$heatmap') {
            return await this.runHeatmapPipelineSteps(event, kafkaAcks)
        }

        const dropOldResult = await this.runStep<PluginEvent | null, typeof dropOldEventsStep>(
            dropOldEventsStep,
            [this, event, team],
            event.team_id
        )
        if (!isOkResult(dropOldResult)) {
            return dropOldResult
        }
        const dropOldEventsResult = dropOldResult.value

        if (dropOldEventsResult == null) {
            // Event was dropped because it's too old.
            return drop('Event too old')
        }

        const transformResult = await this.runStep<TransformationResult, typeof transformEventStep>(
            transformEventStep,
            [dropOldEventsResult, this.hogTransformer],
            event.team_id
        )
        if (!isOkResult(transformResult)) {
            return transformResult
        }
        const { event: transformedEvent } = transformResult.value

        if (transformedEvent === null) {
            return drop('Event dropped by transformation')
        }

        const normalizeResult = await this.runStep<[PluginEvent, DateTime], typeof normalizeEventStep>(
            normalizeEventStep,
            [transformedEvent, processPerson, this.headers, this.hub.TIMESTAMP_COMPARISON_LOGGING_SAMPLE_RATE],
            event.team_id
        )
        if (!isOkResult(normalizeResult)) {
            return normalizeResult
        }
        const [normalizedEvent, timestamp] = normalizeResult.value

        const personStepResult = await this.runPipelineStep<
            [PluginEvent, Person, Promise<void>],
            typeof processPersonsStep
        >(
            processPersonsStep,
            [this, normalizedEvent, team, timestamp, processPerson, this.personsStoreForBatch],
            event.team_id
        )

        if (!isOkResult(personStepResult)) {
            return personStepResult
        }

        const [postPersonEvent, person, personKafkaAck] = personStepResult.value
        kafkaAcks.push(personKafkaAck)

        const prepareResult = await this.runStep<PreIngestionEvent, typeof prepareEventStep>(
            prepareEventStep,
            [this, postPersonEvent, processPerson],
            event.team_id
        )
        if (!isOkResult(prepareResult)) {
            return prepareResult
        }
        const preparedEvent = prepareResult.value

        // TRICKY: old client might still be sending heatmap_data as passengers on other events
        // so this step is here even though up-to-date clients will be sending heatmap events
        // for separate processing
        const extractResult = await this.runStep<[PreIngestionEvent, Promise<void>[]], typeof extractHeatmapDataStep>(
            extractHeatmapDataStep,
            [this, preparedEvent],
            event.team_id
        )
        if (!isOkResult(extractResult)) {
            return extractResult
        }
        const [preparedEventWithoutHeatmaps, heatmapKafkaAcks] = extractResult.value

        if (heatmapKafkaAcks.length > 0) {
            heatmapKafkaAcks.forEach((ack) => kafkaAcks.push(ack))
        }

        const createResult = await this.runStep<RawKafkaEvent, typeof createEventStep>(
            createEventStep,
            [this, preparedEventWithoutHeatmaps, person, processPerson],
            event.team_id
        )
        if (!isOkResult(createResult)) {
            return createResult
        }
        const rawEvent = createResult.value

        const emitResult = await this.runStep<[Promise<void>], typeof emitEventStep>(
            emitEventStep,
            [this, rawEvent],
            event.team_id
        )
        if (!isOkResult(emitResult)) {
            return emitResult
        }
        const clickhouseAck = emitResult.value
        kafkaAcks.push(...clickhouseAck)

        // Create success result with ACK promises
        const successResult: EventPipelineResult = {
            ackPromises: kafkaAcks,
            lastStep: 'emitEventStep',
            args: [rawEvent],
        }

        return ok(successResult)
    }

    registerLastStep(stepName: string, args: any[], ackPromises?: Array<Promise<void>>): EventPipelineResult {
        pipelineLastStepCounter.labels(stepName).inc()
        return {
            ackPromises,
            lastStep: stepName,
            args,
        }
    }

    private reportStalled(stepName: string) {
        pipelineStepStalledCounter.labels(stepName).inc()
    }

    protected async runStep<T, Step extends (...args: any[]) => Promise<T>>(
        step: Step,
        args: Parameters<Step>,
        teamId: number,
        sentToDql = true
    ): Promise<PipelineResult<T>> {
        const timer = new Date()
        const sendException = false
        const timeout = timeoutGuard(
            `Event pipeline step stalled. Timeout warning after ${this.hub.PIPELINE_STEP_STALLED_LOG_TIMEOUT} sec! step=${step.name} team_id=${teamId} distinct_id=${this.originalEvent.distinct_id}`,
            () => ({
                step: step.name,
                teamId: teamId,
                event_name: this.originalEvent.event,
                distinctId: this.originalEvent.distinct_id,
            }),
            this.hub.PIPELINE_STEP_STALLED_LOG_TIMEOUT * 1000,
            sendException,
            this.reportStalled.bind(this, step.name)
        )
        try {
            const result = await step(...args)
            pipelineStepMsSummary.labels(step.name).observe(Date.now() - timer.getTime())
            return ok(result)
        } catch (err) {
            return this.mapError<T>(err, step.name, args, teamId, sentToDql)
        } finally {
            clearTimeout(timeout)
        }
    }

    protected async runPipelineStep<T, Step extends (...args: any[]) => Promise<PipelineResult<T>>>(
        step: Step,
        args: Parameters<Step>,
        teamId: number,
        sentToDql = true
    ): Promise<PipelineResult<T>> {
        const timer = new Date()
        const sendException = false
        const timeout = timeoutGuard(
            `Event pipeline step stalled. Timeout warning after ${this.hub.PIPELINE_STEP_STALLED_LOG_TIMEOUT} sec! step=${step.name} team_id=${teamId} distinct_id=${this.originalEvent.distinct_id}`,
            () => ({
                step: step.name,
                teamId: teamId,
                event_name: this.originalEvent.event,
                distinctId: this.originalEvent.distinct_id,
            }),
            this.hub.PIPELINE_STEP_STALLED_LOG_TIMEOUT * 1000,
            sendException,
            this.reportStalled.bind(this, step.name)
        )
        try {
            const result = await step(...args)
            pipelineStepMsSummary.labels(step.name).observe(Date.now() - timer.getTime())
            return result
        } catch (err) {
            return this.mapError<T>(err, step.name, args, teamId, sentToDql)
        } finally {
            clearTimeout(timeout)
        }
    }

    private shouldRetry(err: any): boolean {
        if (err instanceof DependencyUnavailableError) {
            // If this is an error with a dependency that we control, we want to
            // ensure that the caller knows that the event was not processed,
            // for a reason that we control and that is transient.
            return true
        }
        // Drop events for known non-retryable person merge limit condition
        if (err instanceof PersonMergeLimitExceededError) {
            return false
        }
        // TODO: Disallow via env of errors we're going to put into DLQ instead of taking Kafka lag
        return false
    }

    private mapError<T>(
        err: any,
        currentStepName: string,
        currentArgs: any,
        teamId: number,
        sentToDql: boolean
    ): PipelineResult<T> {
        logger.error('🔔', 'step_failed', { currentStepName, err })
        captureException(err, {
            tags: { team_id: teamId, pipeline_step: currentStepName },
            extra: { currentArgs, originalEvent: this.originalEvent },
        })

        pipelineStepErrorCounter.labels(currentStepName).inc()

        // Should we throw or should we drop and send the event to DLQ.
        if (this.shouldRetry(err)) {
            pipelineStepThrowCounter.labels(currentStepName).inc()
            throw err
        }

        if (sentToDql) {
            return dlq<T>(`Step error - ${currentStepName}`, err)
        }

        // These errors are dropped rather than retried - throw StepErrorNoRetry which will be caught at the pipeline level
        throw new StepErrorNoRetry(currentStepName, currentArgs, err.message)
    }
}
