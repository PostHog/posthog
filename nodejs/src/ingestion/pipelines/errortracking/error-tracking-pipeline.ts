import { Message } from 'node-rdkafka'

import { ReadOnlyGroupTypeManager } from '~/common/groups/readonly-group-type-manager'
import {
    AppMetricsOutput,
    DlqOutput,
    EVENTS_OUTPUT,
    EventOutput,
    IngestionWarningsOutput,
    OverflowOutput,
    TophogOutput,
} from '~/common/outputs'
import { IngestionOutputs } from '~/common/outputs/ingestion-outputs'
import { PersonReadRepository } from '~/common/persons/repositories/person-repository'
import { ErrorTrackingSettings, ErrorTrackingSettingsManager } from '~/common/utils/error-tracking-settings-manager'
import { EventIngestionRestrictionManager } from '~/common/utils/event-ingestion-restrictions'
import { PromiseScheduler } from '~/common/utils/promise-scheduler'
import { TeamManager } from '~/common/utils/team-manager'
import { CommonTeamStage, newCommonIngestionPipeline } from '~/ingestion/common/common-ingestion-pipeline'
import { CookielessManager } from '~/ingestion/common/cookieless/cookieless-manager'
import { OverflowRedirectService } from '~/ingestion/common/overflow-redirect/overflow-redirect-service'
import {
    createApplyCookielessProcessingStep,
    createApplyEventRestrictionsStep,
    createOnlyCookielessRateLimitToOverflowStep,
    createOverflowLaneTTLRefreshStep,
    createSkipCookielessRateLimitToOverflowStep,
} from '~/ingestion/common/steps/event-preprocessing'
import { createCreateEventStep } from '~/ingestion/common/steps/event-processing/create-event-step'
import { EmitEventStepOutput, createEmitEventStep } from '~/ingestion/common/steps/event-processing/emit-event-step'
import { createFetchPersonChunkStep } from '~/ingestion/common/steps/event-processing/fetch-person-chunk-step'
import { createHogTransformEventStep } from '~/ingestion/common/steps/event-processing/hog-transform-event-step'
import { createReadOnlyProcessGroupsStep } from '~/ingestion/common/steps/event-processing/readonly-process-groups-step'
import { createRecordIngestionLagStep } from '~/ingestion/common/steps/record-ingestion-lag'
import { IngestionOverflowMode } from '~/ingestion/config'
import { BatchingContext, BatchingPipeline } from '~/ingestion/framework/batching-pipeline'
import { TopHogRegistry, count, countOk, createTopHogWrapper } from '~/ingestion/framework/extensions/tophog'
import { createBatch } from '~/ingestion/framework/helpers'
import { PluginEvent } from '~/plugin-scaffold'
import { Team } from '~/types'

import { createAttachMessageBytesStep } from './attach-message-bytes-step'
import { createCymbalProcessingStep } from './cymbal-processing-step'
import { CymbalClient } from './cymbal/client'
import { ErrorTrackingHogTransformer } from './error-tracking-consumer'
import { KeyedRateLimiterStepOptions, createKeyedRateLimiterStep } from './keyed-rate-limiter-step'
import { createLoadErrorTrackingSettingsStep } from './load-error-tracking-settings-step'
import { createErrorTrackingPrepareEventStep } from './prepare-event-step'

export interface ErrorTrackingPipelineInput {
    message: Message
}

/**
 * The final step emits to Kafka and outputs handles to the in-flight
 * emissions. Successful events are produced to the output topic, while
 * failures are handled by the result handling pipeline (DLQ, drop, redirect).
 */
export type ErrorTrackingPipelineOutput = EmitEventStepOutput

export type ErrorTrackingPipeline = BatchingPipeline<
    ErrorTrackingPipelineInput,
    ErrorTrackingPipelineOutput,
    { message: Message },
    Record<never, object>,
    { message: Message } & BatchingContext,
    OverflowOutput
>

export type ErrorTrackingOutputs = IngestionOutputs<
    EventOutput | IngestionWarningsOutput | DlqOutput | OverflowOutput | TophogOutput | AppMetricsOutput
>

export interface ErrorTrackingPipelineConfig {
    outputs: ErrorTrackingOutputs
    promiseScheduler: PromiseScheduler
    teamManager: TeamManager
    personRepository: PersonReadRepository
    hogTransformer: ErrorTrackingHogTransformer | null
    cymbalClient: CymbalClient
    groupTypeManager: ReadOnlyGroupTypeManager
    cookielessManager: CookielessManager
    eventIngestionRestrictionManager: EventIngestionRestrictionManager
    overflowMode: IngestionOverflowMode
    /**
     * When true, overflow redirects (both restriction-driven force-overflow
     * and rate-limit-to-overflow) keep the original partition key. When
     * false, redirects emit with a null key so Kafka spreads load across
     * overflow-topic partitions. Cymbal cache locality is enforced one layer
     * down (team_id consistent hashing inside `CymbalClient`), so the
     * partition key on the overflow lane doesn't affect symbolication cache
     * hits.
     */
    preservePartitionLocality: boolean
    /** Service for rate limiting and redirecting to overflow (main lane only). */
    overflowRedirectService?: OverflowRedirectService
    /** Service for refreshing TTLs on overflow lane events. */
    overflowLaneTTLRefreshService?: OverflowRedirectService
    /**
     * Rate limiter step specs to apply post-Cymbal. Each becomes its own batch step in
     * the pipeline, run in array order. Empty / undefined → no rate limiting.
     */
    postCymbalRateLimiters?: KeyedRateLimiterStepOptions<PostCymbalRateLimiterInput>[]
    /**
     * When provided, an error-tracking-settings load step runs before the rate limiter
     * chain so per-team overrides can be read synchronously from the input.
     */
    errorTrackingSettingsManager?: ErrorTrackingSettingsManager
    /** TopHog registry for metrics. */
    topHog: TopHogRegistry
}

/**
 * Shape consumed by post-Cymbal rate limiter step specs. The pipeline guarantees these
 * fields are present at the insertion point (after Cymbal, before enrichment).
 */
export interface PostCymbalRateLimiterInput {
    team: { id: number }
    event: PluginEvent
    errorTrackingSettings?: ErrorTrackingSettings | null
}

/**
 * Apply each rate limiter spec as its own post-Cymbal chunk step. The chain's TCurrent
 * is wider than the spec's input type, but `KeyedRateLimiterStepOptions<T>` is
 * contravariant in T, so a narrower spec assigns into the wider chain context.
 */
function applyKeyedRateLimiters<
    TInput extends { message: Message },
    TContext extends { message: Message },
    ROut extends string,
    CBatch,
    TPost extends { team: Team },
    TCurrent,
>(
    stage: CommonTeamStage<TInput, TContext, ROut, CBatch, TPost, TCurrent>,
    specs: KeyedRateLimiterStepOptions<TCurrent>[]
): CommonTeamStage<TInput, TContext, ROut, CBatch, TPost, TCurrent> {
    return specs.reduce((s, spec) => s.pipeChunk(createKeyedRateLimiterStep(spec)), stage)
}

/**
 * Creates the error tracking pipeline.
 *
 * The pipeline processes exception events through these phases:
 *  1. Parse headers - Extract token, timestamps from Kafka message headers
 *  2. Apply event restrictions - Billing limits, drop/overflow
 *  3. Skip-cookieless rate limit - Redirect non-cookieless rate-limited events to overflow
 *     pre-parse (cookieless events pass through to step 6)
 *  4. Parse Kafka message - Parse message body into event
 *  5. Resolve team - Look up team by token
 *  6. Apply cookieless processing - Rewrite distinct_id for cookieless events
 *  7. Only-cookieless rate limit - Redirect cookieless rate-limited events to overflow
 *     using the hashed distinct_id from step 6
 *  8. Cymbal processing - Symbolicate, fingerprint, and link issues
 *  9. Team-global rate limit - Drop events that exceed per-team caps (optional)
 * 10. Person properties - Fetch person by distinct_id (read-only)
 * 11. Hog transformations - Run team transformations (including GeoIP if enabled)
 * 12. Prepare event - Convert to PreIngestionEvent format, track if person found
 * 13. Group type mapping - Map group types to indexes (read-only)
 * 14. Create event - Build ErrorTrackingKafkaEvent (matches Cymbal's output format)
 * 15. Emit event - Produce to output topic
 *
 * Note: Cymbal runs before enrichment because it only needs the raw exception data
 * for symbolication and fingerprinting. This reduces payload size and avoids
 * wasted enrichment work if Cymbal suppresses the event.
 */
export function createErrorTrackingPipeline(config: ErrorTrackingPipelineConfig): ErrorTrackingPipeline {
    const {
        outputs,
        promiseScheduler,
        teamManager,
        personRepository,
        hogTransformer,
        cymbalClient,
        groupTypeManager,
        cookielessManager,
        eventIngestionRestrictionManager,
        overflowMode,
        preservePartitionLocality,
        overflowRedirectService,
        overflowLaneTTLRefreshService,
        postCymbalRateLimiters,
        errorTrackingSettingsManager,
        topHog,
    } = config

    const topHogWrapper = createTopHogWrapper(topHog)

    const preCymbal = newCommonIngestionPipeline<ErrorTrackingPipelineInput, { message: Message }, OverflowOutput>({
        teamManager,
        outputs,
        promiseScheduler,
        concurrentBatches: 1,
    })
        // Header-only steps: parse Kafka headers and apply token-level restrictions.
        // Cheap; runs per-event before we touch the body.
        .parseHeaders()
        .pipe(
            createApplyEventRestrictionsStep(eventIngestionRestrictionManager, {
                overflowMode,
                preservePartitionLocality,
            })
        )
        // Rate-limit non-cookieless events to overflow before parsing the body.
        // Cookieless events (headers.distinct_id === sentinel) pass through and are
        // handled post-cookieless by createOnlyCookielessRateLimitToOverflowStep, which
        // keys on the hashed distinct_id assigned by the cookieless step.
        .pipeChunk(createSkipCookielessRateLimitToOverflowStep(preservePartitionLocality, overflowRedirectService))
        .parseMessage()
        .resolveTeam({
            wrap: (step) =>
                topHogWrapper(step, [
                    countOk('resolved_teams', (output) => ({
                        team_id: String(output.team.id),
                    })),
                ]),
        })
        // Attach per-team error-tracking settings. No-op when the manager isn't wired
        // (rate limiter disabled) — keeps the type chain consistent regardless.
        .pipe(createLoadErrorTrackingSettingsStep(errorTrackingSettingsManager))
        // Carry the Kafka message byte size through for Cymbal batch chunking.
        .pipe(createAttachMessageBytesStep())
        // Cookieless processing: rewrites event.distinct_id for cookieless
        // events. Must run as a batch and before any step that depends on
        // the final distinct ID.
        .gather()
        .pipeChunk(createApplyCookielessProcessingStep(cookielessManager))
        // Rate-limit only cookieless events to overflow now that they
        // have a real hashed distinct_id. Non-cookieless events were
        // rate-limited pre-parse above.
        .pipeChunk(createOnlyCookielessRateLimitToOverflowStep(preservePartitionLocality, overflowRedirectService))
        // Refresh TTLs for overflow lane events (keeps Redis flags alive)
        .pipeChunk(createOverflowLaneTTLRefreshStep(overflowLaneTTLRefreshService))

    const afterCymbal = preCymbal
        // Process through Cymbal as a batch (before enrichment - Cymbal only
        // needs raw exception data, not person/geoip/group data).
        // Retry on transient failures (5xx, timeout, network errors).
        // 3 retries keeps the worst-case batch time (3 × 45s timeout =
        // 135s) well within the 180s liveness interval, and reduces
        // amplification pressure on Cymbal during degradation.
        .pipeChunk(createCymbalProcessingStep(cymbalClient), {
            retry: { tries: 3, sleepMs: 100, name: 'cymbal_processing' },
        })

    // Post-Cymbal team-global rate-limit chain. Drops events the team
    // has explicitly capped. Empty / undefined → no-op.
    return (
        applyKeyedRateLimiters(afterCymbal, postCymbalRateLimiters ?? [])
            // Batch fetch person (read-only, no updates)
            .pipeChunk(createFetchPersonChunkStep(personRepository))
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
            .pipe(createRecordIngestionLagStep())
            .build()
    )
}

/**
 * Runs a batch of messages through the error tracking pipeline.
 *
 * Events are emitted to the output topic as a side effect. Failures are
 * handled by the result handling pipeline (DLQ, drop, redirect).
 *
 * All side effects — element results and batch hooks alike — are handled
 * inside the pipeline (scheduled on the promise scheduler, which the consumer
 * drains before committing offsets), so this driver only drains results.
 */
export async function runErrorTrackingPipeline(pipeline: ErrorTrackingPipeline, messages: Message[]): Promise<void> {
    if (messages.length === 0) {
        return
    }

    const batch = createBatch(messages.map((message) => ({ message })))
    // The consumer drains each batch fully before feeding the next and the hooks
    // always succeed, so a rejected feed can only be a framework invariant violation.
    const feedResult = await pipeline.feed(batch)
    if (!feedResult.ok) {
        throw new Error(`error tracking pipeline rejected feed: ${feedResult.kind} (${feedResult.reason})`)
    }

    while ((await pipeline.next()) !== null) {
        // Drain all results
    }
}
