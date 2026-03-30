import { Message } from 'node-rdkafka'

import { EventIngestionRestrictionManager } from '~/utils/event-ingestion-restrictions'
import { PromiseScheduler } from '~/utils/promise-scheduler'
import { TeamManager } from '~/utils/team-manager'
import { GroupTypeManager } from '~/worker/ingestion/group-type-manager'
import { PersonRepository } from '~/worker/ingestion/persons/repositories/person-repository'

import { DlqOutput, EVENTS_OUTPUT, EventOutput, IngestionWarningsOutput, OverflowOutput } from '../common/outputs'
import {
    createApplyEventRestrictionsStep,
    createOverflowLaneTTLRefreshStep,
    createParseHeadersStep,
    createParseKafkaMessageStep,
    createRateLimitToOverflowStep,
    createResolveTeamStep,
} from '../event-preprocessing'
import { createCreateEventStep } from '../event-processing/create-event-step'
import { createEmitEventStep } from '../event-processing/emit-event-step'
import { createHogTransformEventStep } from '../event-processing/hog-transform-event-step'
import { createReadOnlyProcessGroupsStep } from '../event-processing/readonly-process-groups-step'
import { IngestionOutputs } from '../outputs/ingestion-outputs'
import { BatchPipelineUnwrapper } from '../pipelines/batch-pipeline-unwrapper'
import { newBatchPipelineBuilder } from '../pipelines/builders'
import { TopHogRegistry, count, countOk, createTopHogWrapper } from '../pipelines/extensions/tophog'
import { createBatch, createUnwrapper } from '../pipelines/helpers'
import { PipelineConfig } from '../pipelines/result-handling-pipeline'
import { ok } from '../pipelines/results'
import { OverflowRedirectService } from '../utils/overflow-redirect/overflow-redirect-service'
import { createCymbalProcessingStep } from './cymbal-processing-step'
import { CymbalClient } from './cymbal/client'
import { ErrorTrackingHogTransformer } from './error-tracking-consumer'
import { createFetchPersonBatchStep } from './person-properties-step'
import { createErrorTrackingPrepareEventStep } from './prepare-event-step'

export interface ErrorTrackingPipelineInput {
    message: Message
}

/**
 * The pipeline output is void because the final step emits to Kafka.
 * Successful events are produced to the output topic, while failures
 * are handled by the result handling pipeline (DLQ, drop, redirect).
 */
export type ErrorTrackingPipelineOutput = void

export type ErrorTrackingOutputs = IngestionOutputs<EventOutput | IngestionWarningsOutput | DlqOutput | OverflowOutput>

export interface ErrorTrackingPipelineConfig {
    outputs: ErrorTrackingOutputs
    groupId: string
    promiseScheduler: PromiseScheduler
    teamManager: TeamManager
    personRepository: PersonRepository
    hogTransformer: ErrorTrackingHogTransformer | null
    cymbalClient: CymbalClient
    groupTypeManager: GroupTypeManager
    eventIngestionRestrictionManager: EventIngestionRestrictionManager
    overflowEnabled: boolean
    /** Service for rate limiting and redirecting to overflow (main lane only). */
    overflowRedirectService?: OverflowRedirectService
    /** Service for refreshing TTLs on overflow lane events. */
    overflowLaneTTLRefreshService?: OverflowRedirectService
    /** TopHog registry for metrics. */
    topHog: TopHogRegistry
}

/**
 * Creates the error tracking pipeline.
 *
 * The pipeline processes exception events through these phases:
 * 1. Parse headers - Extract token, timestamps from Kafka message headers
 * 2. Apply event restrictions - Billing limits, drop/overflow
 * 3. Parse Kafka message - Parse message body into event
 * 4. Resolve team - Look up team by token
 * 5. Cymbal processing - Symbolicate, fingerprint, and link issues
 * 6. Person properties - Fetch person by distinct_id (read-only)
 * 7. Hog transformations - Run team transformations (including GeoIP if enabled)
 * 8. Prepare event - Convert to PreIngestionEvent format, track if person found
 * 9. Group type mapping - Map group types to indexes (read-only)
 * 10. Create event - Build ErrorTrackingKafkaEvent (matches Cymbal's output format)
 * 11. Emit event - Produce to output topic
 *
 * Note: Cymbal runs before enrichment because it only needs the raw exception data
 * for symbolication and fingerprinting. This reduces payload size and avoids
 * wasted enrichment work if Cymbal suppresses the event.
 */
export function createErrorTrackingPipeline(
    config: ErrorTrackingPipelineConfig
): BatchPipelineUnwrapper<
    ErrorTrackingPipelineInput,
    ErrorTrackingPipelineOutput,
    { message: Message },
    OverflowOutput
> {
    const {
        outputs,
        groupId,
        promiseScheduler,
        teamManager,
        personRepository,
        hogTransformer,
        cymbalClient,
        groupTypeManager,
        eventIngestionRestrictionManager,
        overflowEnabled,
        overflowRedirectService,
        overflowLaneTTLRefreshService,
        topHog,
    } = config

    const topHogWrapper = createTopHogWrapper(topHog)

    const pipelineConfig: PipelineConfig<OverflowOutput> = {
        outputs,
        promiseScheduler,
    }

    const pipeline = newBatchPipelineBuilder<ErrorTrackingPipelineInput, { message: Message }>()
        .messageAware((b) =>
            b
                .sequentially((b) =>
                    b
                        // Parse headers from Kafka message [REUSE]
                        .pipe(createParseHeadersStep())
                        // Apply event restrictions (billing limits, drop/overflow) [REUSE]
                        .pipe(
                            createApplyEventRestrictionsStep(eventIngestionRestrictionManager, {
                                overflowEnabled,
                                preservePartitionLocality: true,
                            })
                        )
                        // Parse Kafka message body [REUSE]
                        .pipe(createParseKafkaMessageStep())
                        // Resolve team from token [REUSE]
                        .pipe(
                            topHogWrapper(createResolveTeamStep(teamManager), [
                                countOk('resolved_teams', (output) => ({
                                    team_id: String(output.team.id),
                                })),
                            ])
                        )
                )
                // Map team to context for handleIngestionWarnings, and carry
                // the Kafka message byte size through for Cymbal batch chunking.
                .filterMap(
                    (element) => ({
                        result: ok({
                            ...element.result.value,
                            messageBytes: element.context.message.value?.length ?? 0,
                        }),
                        context: {
                            ...element.context,
                            team: { id: element.result.value.team.id },
                        },
                    }),
                    (b) =>
                        b
                            .teamAware((b) =>
                                b
                                    .gather()
                                    // Rate limit high-volume token:distinct_id pairs to overflow
                                    .pipeBatch(
                                        createRateLimitToOverflowStep(
                                            true, // preservePartitionLocality
                                            overflowRedirectService
                                        )
                                    )
                                    // Refresh TTLs for overflow lane events (keeps Redis flags alive)
                                    .pipeBatch(createOverflowLaneTTLRefreshStep(overflowLaneTTLRefreshService))
                                    // Process through Cymbal as a batch (before enrichment - Cymbal only
                                    // needs raw exception data, not person/geoip/group data).
                                    // Retry on transient failures (5xx, timeout, network errors).
                                    .pipeBatchWithRetry(createCymbalProcessingStep(cymbalClient), {
                                        tries: 3,
                                        sleepMs: 100,
                                    })
                                    // Enrich, prepare, create, and emit events
                                    // Batch fetch person (read-only, no updates)
                                    .pipeBatch(createFetchPersonBatchStep(personRepository))
                                    .sequentially((b) =>
                                        b
                                            // Run Hog transformations (including GeoIP if team has it enabled)
                                            .pipe(createHogTransformEventStep(hogTransformer))
                                            // Prepare event for emission
                                            .pipe(createErrorTrackingPrepareEventStep())
                                            // Map group types to indexes (read-only, no new group types created)
                                            .pipe(createReadOnlyProcessGroupsStep(groupTypeManager))
                                            .pipe(createCreateEventStep(EVENTS_OUTPUT))
                                            .pipe(
                                                topHogWrapper(
                                                    createEmitEventStep({
                                                        outputs,
                                                        groupId,
                                                    }),
                                                    [
                                                        count('emitted_events', (input) => ({
                                                            team_id: String(input.teamId),
                                                        })),
                                                        count('emitted_events_per_distinct_id', (input) => ({
                                                            team_id: String(input.teamId),
                                                            distinct_id: input.eventsToEmit[0]?.event.distinct_id ?? '',
                                                        })),
                                                    ]
                                                )
                                            )
                                    )
                            )
                            .handleIngestionWarnings(outputs)
                )
        )
        .handleResults(pipelineConfig)
        .handleSideEffects(promiseScheduler, { await: false })
        .gather()
        .build()

    return createUnwrapper(pipeline)
}

/**
 * Runs a batch of messages through the error tracking pipeline.
 *
 * Events are emitted to the output topic as a side effect. Failures are
 * handled by the result handling pipeline (DLQ, drop, redirect).
 */
export async function runErrorTrackingPipeline(
    pipeline: BatchPipelineUnwrapper<
        ErrorTrackingPipelineInput,
        ErrorTrackingPipelineOutput,
        { message: Message },
        OverflowOutput
    >,
    messages: Message[]
): Promise<void> {
    if (messages.length === 0) {
        return
    }

    const batch = createBatch(messages.map((message) => ({ message })))
    pipeline.feed(batch)

    while ((await pipeline.next()) !== null) {
        // Drain all results
    }
}
