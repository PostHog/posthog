import { DateTime } from 'luxon'

import { PluginEvent } from '@posthog/plugin-scaffold'

import { HogTransformerService, TransformationResult } from '../../../cdp/hog-transformations/hog-transformer.service'
import { PipelineWarning } from '../../../ingestion/pipelines/pipeline.interface'
import { PipelineResult, dlq, drop, isOkResult, ok } from '../../../ingestion/pipelines/results'
import {
    EventHeaders,
    Hub,
    JwtVerificationStatus,
    Person,
    PipelineEvent,
    PreIngestionEvent,
    RawKafkaEvent,
    Team,
} from '../../../types'
import { DependencyUnavailableError } from '../../../utils/db/error'
import { timeoutGuard } from '../../../utils/db/utils'
import { logger } from '../../../utils/logger'
import { captureException } from '../../../utils/posthog'
import { GroupStoreForBatch } from '../groups/group-store-for-batch.interface'
import { PersonMergeLimitExceededError } from '../persons/person-merge-types'
import { MergeMode, determineMergeMode } from '../persons/person-merge-types'
import { PersonsStoreForBatch } from '../persons/persons-store-for-batch'
import { EventsProcessor } from '../process-event'
import { createEventStep } from './createEventStep'
import { dropOldEventsStep } from './dropOldEventsStep'
import { extractHeatmapDataStep } from './extractHeatmapDataStep'
import {
    pipelineLastStepCounter,
    pipelineStepErrorCounter,
    pipelineStepMsSummary,
    pipelineStepStalledCounter,
    pipelineStepThrowCounter,
} from './metrics'
import { normalizeEventStep } from './normalizeEventStep'
import { prepareEventStep } from './prepareEventStep'
import { processPersonlessStep } from './processPersonlessStep'
import { processPersonsStep } from './processPersonsStep'
import { transformEventStep } from './transformEventStep'

export type EventPipelineResult = {
    // Only used in tests
    // TODO: update to test for side-effects of running the pipeline rather than
    // this return type.
    lastStep: string
    eventToEmit?: RawKafkaEvent
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
    verified: JwtVerificationStatus

    constructor(
        hub: Hub,
        event: PipelineEvent,
        hogTransformer: HogTransformerService | null = null,
        personsStoreForBatch: PersonsStoreForBatch,
        groupStoreForBatch: GroupStoreForBatch,
        headers?: EventHeaders,
        verified: JwtVerificationStatus = JwtVerificationStatus.NotVerified
    ) {
        this.hub = hub
        this.originalEvent = event
        this.eventsProcessor = new EventsProcessor(hub)
        this.hogTransformer = hogTransformer
        this.personsStoreForBatch = personsStoreForBatch
        this.groupStoreForBatch = groupStoreForBatch
        this.mergeMode = determineMergeMode(hub)
        this.headers = headers
        this.verified = verified
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
        kafkaAcks: Promise<unknown>[],
        warnings: PipelineWarning[]
    ): Promise<EventPipelinePipelineResult> {
        const processPerson = false

        const normalizeResult = await this.runStep<[PluginEvent, DateTime], typeof normalizeEventStep>(
            normalizeEventStep,
            [event, processPerson],
            event.team_id,
            true,
            kafkaAcks,
            warnings
        )
        if (!isOkResult(normalizeResult)) {
            // TODO: We pass kafkaAcks, so the side effects should be merged, but this needs to be refactored
            return normalizeResult
        }
        const [normalizedEvent] = normalizeResult.value

        const prepareResult = await this.runStep<PreIngestionEvent, typeof prepareEventStep>(
            prepareEventStep,
            [this, normalizedEvent, processPerson],
            event.team_id,
            true,
            kafkaAcks,
            warnings
        )
        if (!isOkResult(prepareResult)) {
            // TODO: We pass kafkaAcks, so the side effects should be merged, but this needs to be refactored
            return prepareResult
        }
        const preparedEvent = prepareResult.value

        const extractResult = await this.runStep<
            [PreIngestionEvent, Promise<unknown>[]],
            typeof extractHeatmapDataStep
        >(extractHeatmapDataStep, [this, preparedEvent], event.team_id, true, kafkaAcks, warnings)
        if (!isOkResult(extractResult)) {
            // TODO: We pass kafkaAcks, so the side effects should be merged, but this needs to be refactored
            return extractResult
        }
        const [_, heatmapKafkaAcks] = extractResult.value

        if (heatmapKafkaAcks.length > 0) {
            heatmapKafkaAcks.forEach((ack) => kafkaAcks.push(ack))
        }

        const result = this.registerLastStep('extractHeatmapDataStep')
        return ok(result, kafkaAcks, warnings)
    }

    async runEventPipeline(
        event: PipelineEvent,
        team: Team,
        processPerson: boolean = true,
        forceDisablePersonProcessing: boolean = false
    ): Promise<EventPipelinePipelineResult> {
        this.originalEvent = event

        try {
            const pluginEvent: PluginEvent = {
                ...event,
                team_id: team.id,
            }
            return await this.runEventPipelineSteps(pluginEvent, team, processPerson, forceDisablePersonProcessing)
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

    async runEventPipelineSteps(
        event: PluginEvent,
        team: Team,
        processPerson: boolean,
        forceDisablePersonProcessing: boolean
    ): Promise<EventPipelinePipelineResult> {
        const kafkaAcks: Promise<unknown>[] = []
        const warnings: PipelineWarning[] = []

        if (event.event === '$$heatmap') {
            return await this.runHeatmapPipelineSteps(event, kafkaAcks, warnings)
        }

        const dropOldResult = await this.runStep<PluginEvent | null, typeof dropOldEventsStep>(
            dropOldEventsStep,
            [this, event, team],
            event.team_id,
            true,
            kafkaAcks,
            warnings
        )
        if (!isOkResult(dropOldResult)) {
            // TODO: We pass kafkaAcks, so the side effects should be merged, but this needs to be refactored
            return dropOldResult
        }
        const dropOldEventsResult = dropOldResult.value

        if (dropOldEventsResult == null) {
            // TODO: We pass kafkaAcks, so the side effects should be merged, but this needs to be refactored
            return drop('event_too_old', kafkaAcks, warnings)
        }

        const transformResult = await this.runStep<TransformationResult, typeof transformEventStep>(
            transformEventStep,
            [dropOldEventsResult, this.hogTransformer],
            event.team_id,
            true,
            kafkaAcks,
            warnings
        )
        if (!isOkResult(transformResult)) {
            // TODO: We pass kafkaAcks, so the side effects should be merged, but this needs to be refactored
            return transformResult
        }
        const { event: transformedEvent } = transformResult.value

        if (transformedEvent === null) {
            // TODO: We pass kafkaAcks, so the side effects should be merged, but this needs to be refactored
            return drop('dropped_by_transformation', kafkaAcks, warnings)
        }

        const normalizeResult = await this.runStep<[PluginEvent, DateTime], typeof normalizeEventStep>(
            normalizeEventStep,
            [transformedEvent, processPerson, this.headers, this.hub.TIMESTAMP_COMPARISON_LOGGING_SAMPLE_RATE],
            event.team_id,
            true,
            kafkaAcks,
            warnings
        )
        if (!isOkResult(normalizeResult)) {
            // TODO: We pass kafkaAcks, so the side effects should be merged, but this needs to be refactored
            return normalizeResult
        }
        const [normalizedEvent, timestamp] = normalizeResult.value

        const personProcessingResult = await this.processPersonForEvent(
            normalizedEvent,
            team,
            timestamp,
            processPerson,
            forceDisablePersonProcessing,
            event.team_id,
            kafkaAcks,
            warnings
        )

        if (!isOkResult(personProcessingResult)) {
            return personProcessingResult
        }

        const { event: postPersonEvent, person, kafkaAck: personKafkaAck } = personProcessingResult.value
        kafkaAcks.push(personKafkaAck)

        const prepareResult = await this.runStep<PreIngestionEvent, typeof prepareEventStep>(
            prepareEventStep,
            [this, postPersonEvent, processPerson],
            event.team_id,
            true,
            kafkaAcks,
            warnings
        )
        if (!isOkResult(prepareResult)) {
            // TODO: We pass kafkaAcks, so the side effects should be merged, but this needs to be refactored
            return prepareResult
        }
        const preparedEvent = prepareResult.value

        // TRICKY: old client might still be sending heatmap_data as passengers on other events
        // so this step is here even though up-to-date clients will be sending heatmap events
        // for separate processing
        const extractResult = await this.runStep<
            [PreIngestionEvent, Promise<unknown>[]],
            typeof extractHeatmapDataStep
        >(extractHeatmapDataStep, [this, preparedEvent], event.team_id, true, kafkaAcks, warnings)
        if (!isOkResult(extractResult)) {
            // TODO: We pass kafkaAcks, so the side effects should be merged, but this needs to be refactored
            return extractResult
        }
        const [preparedEventWithoutHeatmaps, heatmapKafkaAcks] = extractResult.value

        if (heatmapKafkaAcks.length > 0) {
            heatmapKafkaAcks.forEach((ack) => kafkaAcks.push(ack))
        }

        const createResult = await this.runStep<RawKafkaEvent, typeof createEventStep>(
            createEventStep,
            [this, preparedEventWithoutHeatmaps, person, processPerson, this.verified],
            event.team_id,
            true,
            kafkaAcks,
            warnings
        )
        if (!isOkResult(createResult)) {
            // TODO: We pass kafkaAcks, so the side effects should be merged, but this needs to be refactored
            return createResult
        }
        const rawEvent = createResult.value

        const successResult: EventPipelineResult = {
            lastStep: 'createEventStep',
            eventToEmit: rawEvent,
        }

        return ok(successResult, kafkaAcks, warnings)
    }

    private async processPersonForEvent(
        event: PluginEvent,
        team: Team,
        timestamp: DateTime,
        processPerson: boolean,
        forceDisablePersonProcessing: boolean,
        teamId: number,
        kafkaAcks: Promise<unknown>[],
        warnings: PipelineWarning[]
    ): Promise<PipelineResult<{ event: PluginEvent; person: Person; kafkaAck: Promise<void> }>> {
        let postPersonEvent = event
        let person: Person
        let personKafkaAck: Promise<void> = Promise.resolve()
        let shouldProcessPerson = processPerson
        let forceUpgrade = false

        // If personless mode, check if we need to force upgrade
        if (!processPerson) {
            const personlessResult = await this.runPipelineStep<Person, typeof processPersonlessStep>(
                processPersonlessStep,
                [event, team, timestamp, this.personsStoreForBatch, forceDisablePersonProcessing],
                teamId,
                true,
                kafkaAcks,
                warnings
            )

            if (!isOkResult(personlessResult)) {
                return personlessResult
            }

            person = personlessResult.value
            forceUpgrade = !!person.force_upgrade
            shouldProcessPerson = forceUpgrade
        }

        // Run full person processing if needed (either processPerson=true or force_upgrade)
        if (shouldProcessPerson) {
            const personStepResult = await this.runPipelineStep<
                [PluginEvent, Person, Promise<void>],
                typeof processPersonsStep
            >(
                processPersonsStep,
                [this, event, team, timestamp, true, this.personsStoreForBatch],
                teamId,
                true,
                kafkaAcks,
                warnings
            )

            if (!isOkResult(personStepResult)) {
                return personStepResult
            }

            const [processedEvent, processedPerson, ack] = personStepResult.value
            postPersonEvent = processedEvent
            person = processedPerson
            personKafkaAck = ack

            // Preserve force_upgrade flag if it was set by personless step
            if (forceUpgrade) {
                person.force_upgrade = true
            }
        }

        return ok({ event: postPersonEvent, person: person!, kafkaAck: personKafkaAck })
    }

    registerLastStep(stepName: string, eventToEmit?: RawKafkaEvent): EventPipelineResult {
        pipelineLastStepCounter.labels(stepName).inc()
        return {
            lastStep: stepName,
            eventToEmit,
        }
    }

    private reportStalled(stepName: string) {
        pipelineStepStalledCounter.labels(stepName).inc()
    }

    protected async runStep<T, Step extends (...args: any[]) => Promise<T>>(
        step: Step,
        args: Parameters<Step>,
        teamId: number,
        sentToDql = true,
        kafkaAcks: Promise<unknown>[] = [],
        warnings: PipelineWarning[] = []
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
            return ok(result, [], warnings)
        } catch (err) {
            return this.mapError<T>(err, step.name, args, teamId, sentToDql, kafkaAcks, warnings)
        } finally {
            clearTimeout(timeout)
        }
    }

    protected async runPipelineStep<T, Step extends (...args: any[]) => Promise<PipelineResult<T>>>(
        step: Step,
        args: Parameters<Step>,
        teamId: number,
        sentToDql = true,
        kafkaAcks: Promise<unknown>[] = [],
        warnings: PipelineWarning[] = []
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
            // Merge incoming warnings with warnings from the step result
            if (warnings.length > 0) {
                return {
                    ...result,
                    warnings: [...warnings, ...result.warnings],
                }
            }
            return result
        } catch (err) {
            return this.mapError<T>(err, step.name, args, teamId, sentToDql, kafkaAcks, warnings)
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
        sendToDlq: boolean,
        kafkaAcks: Promise<unknown>[] = [],
        warnings: PipelineWarning[] = []
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

        if (sendToDlq) {
            return dlq<T>(`Step error - ${currentStepName}`, err, kafkaAcks, warnings)
        }

        // These errors are dropped rather than retried - throw StepErrorNoRetry which will be caught at the pipeline level
        throw new StepErrorNoRetry(currentStepName, currentArgs, err.message)
    }
}
