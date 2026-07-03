import { Message } from 'node-rdkafka'

import { DlqOutput, IngestionWarningsOutput, OverflowOutput } from '~/common/outputs'
import { IngestionOutputs } from '~/common/outputs/ingestion-outputs'
import { EventIngestionRestrictionManager } from '~/common/utils/event-ingestion-restrictions'
import { PromiseScheduler } from '~/common/utils/promise-scheduler'
import { createApplyEventRestrictionsStep, createParseHeadersStep } from '~/ingestion/common/steps/event-preprocessing'
import { AccumulatingPipeline, AccumulationContext } from '~/ingestion/framework/accumulating-pipeline'
import { BatchPipeline } from '~/ingestion/framework/batch-pipeline.interface'
import { newAccumulatingPipeline, newBatchPipelineBuilder } from '~/ingestion/framework/builders'
import { TopHogRegistry, createTopHogWrapper, sum, timer } from '~/ingestion/framework/extensions/tophog'
import { PipelineConfig } from '~/ingestion/framework/result-handling-pipeline'
import { KafkaOffsetManager } from '~/ingestion/pipelines/sessionreplay/kafka/offset-manager'
import { ParsedMessageData } from '~/ingestion/pipelines/sessionreplay/kafka/types'
import { SessionBatchContext } from '~/ingestion/pipelines/sessionreplay/session-batch-context'
import { SessionBatchFactory } from '~/ingestion/pipelines/sessionreplay/sessions/session-batch-factory'
import { SessionFilter } from '~/ingestion/pipelines/sessionreplay/sessions/session-filter'
import { SessionTracker } from '~/ingestion/pipelines/sessionreplay/sessions/session-tracker'
import { SessionBlockMetadata } from '~/ingestion/pipelines/sessionreplay/shared/metadata/session-block-metadata'
import { RetentionService } from '~/ingestion/pipelines/sessionreplay/shared/retention/retention-service'
import { TeamService } from '~/ingestion/pipelines/sessionreplay/shared/teams/team-service'
import { KeyStore } from '~/ingestion/pipelines/sessionreplay/shared/types'
import { TeamForReplay } from '~/ingestion/pipelines/sessionreplay/teams/types'
import { ValueMatcher } from '~/types'

import { createLibVersionMonitorStep } from './lib-version-monitor-step'
import { createParseMessageStep } from './parse-message-step'
import { createRecordSessionEventStep } from './record-session-event-step'
import { createCommitOffsetsStep } from './session-batch-commit-offsets-step'
import { createMarkSeenStep } from './session-batch-mark-seen-step'
import { createRecordMetricsStep } from './session-batch-record-metrics-step'
import { createResolveRetentionStep } from './session-batch-resolve-retention-step'
import { createCreateSessionBatchStep } from './session-batch-step'
import { createTrackAndGateStep } from './session-batch-track-and-gate-step'
import { createWriteStep } from './session-batch-write-step'
import { createResolveKeyStep } from './session-resolve-key-step'
import { createTeamFilterStep } from './team-filter-step'
import { createValidateSessionReplayHeadersStep } from './validate-headers-step'

export interface SessionReplayPipelineInput {
    message: Message
}

export interface SessionReplayPipelineOutput {
    team: TeamForReplay
    parsedMessage: ParsedMessageData
}

/**
 * The per-message inner pipeline wrapped by the session replay pipeline. Its input carries the
 * batch context (the recorder) tagged on by the accumulating pipeline, which the retention and
 * record steps read.
 */
export type SessionReplayInnerPipeline = BatchPipeline<
    SessionReplayPipelineInput & SessionBatchContext & AccumulationContext, // TInput: raw input + batch recorder + batch id
    SessionReplayPipelineOutput, // TOutput: element out of the inner pipeline
    { message: Message }, // CInput: per-element context in (the Kafka message)
    { message: Message }, // COutput: per-element context out (the Kafka message)
    OverflowOutput // R: redirect output names this pipeline can emit
>

export type SessionReplayPipeline = AccumulatingPipeline<
    SessionReplayPipelineInput, // TRecordIn: element fed in per message (batch context is added internally)
    SessionReplayPipelineOutput, // TRecordOut: element out of the inner pipeline
    { message: Message }, // CRecordIn: inner-pipeline context in (the Kafka message)
    { message: Message }, // CRecordOut: inner-pipeline context out (the Kafka message)
    SessionBatchContext, // CBatch: batch context minted per cycle (the recorder), tagged on every element and the flush unit
    SessionBlockMetadata[], // TFlushOut: element out of the flush pipeline (written block metadata)
    Record<string, never>, // CFlushOut: flush-pipeline context out (empty — the flush unit carries no context)
    OverflowOutput // R: redirect output names this pipeline can emit
>

export interface SessionReplayInnerPipelineConfig {
    outputs: IngestionOutputs<IngestionWarningsOutput | DlqOutput | OverflowOutput>
    eventIngestionRestrictionManager: EventIngestionRestrictionManager
    overflowEnabled: boolean
    promiseScheduler: PromiseScheduler
    teamService: TeamService
    /** Resolves per-session retention before recording, so keys and storage route correctly */
    retentionService: RetentionService
    /** Detects newly-seen sessions during the pre-record session-key resolution. */
    sessionTracker: SessionTracker
    /** Blocks and rate-limits new sessions during the pre-record session-key resolution. */
    sessionFilter: SessionFilter
    /** Resolves per-session encryption keys before recording. */
    keyStore: KeyStore
    /** Caps how many sessions resolve their encryption key concurrently, bounding KMS/DynamoDB fan-out. */
    sessionKeyResolutionMaxConcurrency: number
    /** TopHog registry for tracking metrics. */
    topHog: TopHogRegistry
    /** Debug logging matcher for partition-based debugging. */
    isDebugLoggingEnabled: ValueMatcher<number>
}

export interface SessionReplayPipelineConfig {
    recordPipeline: SessionReplayInnerPipeline
    sessionBatchFactory: SessionBatchFactory
    /** Committed by the commit-offsets flush step after the write step persists the batch */
    offsetManager: KafkaOffsetManager
    /** Maximum raw size (before compression) of a batch in bytes before it is flushed */
    maxBatchSizeBytes: number
    /** Maximum age of a batch in milliseconds before it is flushed */
    maxBatchAgeMs: number
}

/**
 * Creates the session replay inner (per-message) pipeline.
 *
 * The pipeline processes messages through these phases:
 * 1. Restrictions - Parse headers and apply event ingestion restrictions (drop/overflow)
 * 2. Validate headers - Enforce the capture guarantees (DLQ if missing) and narrow the type
 * 3. Team Filter - Validate team ownership and enrich with team context
 * 4. Resolve retention - one batched lookup, keyed on the session_id header, before parse; drop
 *    sessions with unresolvable retention
 * 5. Resolve session key - track the session, rate-limit/block new sessions, and resolve its
 *    encryption key, off the S3 write path; drop blocked/deleted sessions
 * 6. Parse - Parse Kafka messages into structured session recording data (inside teamAware)
 * 7. Version Monitor - Check library version and emit warnings for old versions
 * 8. Record - Fold parsed messages into the cycle's recorder (using the resolved retention and key)
 */
export function createSessionReplayInnerPipeline(config: SessionReplayInnerPipelineConfig): SessionReplayInnerPipeline {
    const {
        outputs,
        eventIngestionRestrictionManager,
        overflowEnabled,
        promiseScheduler,
        teamService,
        retentionService,
        sessionTracker,
        sessionFilter,
        keyStore,
        sessionKeyResolutionMaxConcurrency,
        topHog,
        isDebugLoggingEnabled,
    } = config

    const pipelineConfig: PipelineConfig<OverflowOutput> = {
        outputs,
        promiseScheduler,
    }

    const topHogWrapper = createTopHogWrapper(topHog)

    const pipeline = newBatchPipelineBuilder<
        SessionReplayPipelineInput & SessionBatchContext & AccumulationContext,
        { message: Message }
    >()
        .messageAware((b) =>
            b
                .sequentially((b) =>
                    b
                        // Parse headers and apply restrictions (drop/overflow)
                        .pipe(createParseHeadersStep())
                        .pipe(
                            createApplyEventRestrictionsStep(eventIngestionRestrictionManager, {
                                overflowEnabled,
                                preservePartitionLocality: true, // Sessions must stay on the same partition
                            })
                        )
                        // Validate the headers capture guarantees (DLQ if missing) and narrow the type
                        .pipe(createValidateSessionReplayHeadersStep())
                        // Validate team ownership and enrich with team context
                        .pipe(createTeamFilterStep(teamService))
                )
                // Resolve retention for the whole batch in one call, before the message is parsed and
                // recorded — keyed on the (validated) session_id header. Sessions with unresolvable
                // retention are dropped before any parse or write.
                .gather()
                .pipeBatchWithRetry(createResolveRetentionStep(retentionService), {
                    tries: 3,
                    sleepMs: 100,
                })
                // Track sessions and rate-limit new ones for the whole batch, tagging the survivors with
                // isNewSession and dropping the blocked ones right here (they carry no key, so nothing
                // downstream acts on them). Its own retry scope means a later key-resolution failure never
                // re-runs the rate limiter and double-charges the budget.
                .pipeBatchWithRetry(createTrackAndGateStep(sessionTracker, sessionFilter), {
                    tries: 3,
                    sleepMs: 100,
                })
                // Resolve each session's encryption key. Grouped by session so it runs once per session
                // (the cached keystore fans the key to its other messages) and concurrently across
                // sessions, capped to bound KMS/DynamoDB fan-out. Per-session retry isolates a transient
                // keystore blip to that one session. Deleted sessions are dropped here.
                .groupBy((element) => `${element.team.teamId}:${element.headers.session_id}`)
                .concurrently(
                    (group) =>
                        group.sequentially((b) =>
                            b.retry((rb) => rb.pipe(createResolveKeyStep(keyStore)), {
                                name: 'resolve_session_key',
                                tries: 3,
                                sleepMs: 100,
                            })
                        ),
                    { maxConcurrency: sessionKeyResolutionMaxConcurrency }
                )
                // Re-collect the per-session groups into one batch — both to mark the whole batch seen
                // in a single Redis write and as the barrier that guarantees every key is resolved first.
                .gather()
                // Mark the surviving new sessions seen, now that every key is durably resolved.
                .pipeBatch(createMarkSeenStep(sessionTracker))
                // Map TeamForReplay.teamId to context.team.id for handleIngestionWarnings
                .filterMap(
                    (element) => ({
                        result: element.result,
                        context: {
                            ...element.context,
                            team: { id: element.result.value.team.teamId },
                        },
                    }),
                    (b) =>
                        b
                            .teamAware((b) =>
                                b
                                    .sequentially((b) =>
                                        b
                                            // Parse message content
                                            .pipe(
                                                topHogWrapper(createParseMessageStep(), [
                                                    timer('parse_time_ms_by_session_id', (input) => ({
                                                        token: input.headers.token ?? 'unknown',
                                                        session_id: input.headers.session_id ?? 'unknown',
                                                    })),
                                                ])
                                            )
                                            // Monitor library version and emit warnings for old versions
                                            .pipe(createLibVersionMonitorStep())
                                            // Record to the cycle's recorder (uses the resolved retention and key)
                                            .pipe(
                                                topHogWrapper(
                                                    createRecordSessionEventStep({
                                                        isDebugLoggingEnabled,
                                                    }),
                                                    [
                                                        sum(
                                                            'message_size_by_session_id',
                                                            (input) => ({
                                                                token: input.parsedMessage.token ?? 'unknown',
                                                                session_id: input.parsedMessage.session_id,
                                                            }),
                                                            (input) => input.parsedMessage.metadata.rawSize
                                                        ),
                                                        timer('consume_time_ms_by_session_id', (input) => ({
                                                            token: input.parsedMessage.token ?? 'unknown',
                                                            session_id: input.parsedMessage.session_id,
                                                        })),
                                                    ]
                                                )
                                            )
                                    )
                                    .gather()
                            )
                            .handleIngestionWarnings(outputs)
                )
        )
        .handleResults(pipelineConfig)
        .handleSideEffects(promiseScheduler, { await: false })
        .gather()
        .build()

    return pipeline
}

/**
 * Builds the session replay pipeline: an accumulating pipeline wrapping the per-message inner
 * pipeline. The inner pipeline resolves retention and session keys off the S3 write path, then folds
 * events into a recorder minted per cycle by the factory; the flush pipeline writes the recorder to
 * storage, commits the offsets it covers, then records the flush metrics — all on a size or age
 * trigger.
 */
export function createSessionReplayPipeline(config: SessionReplayPipelineConfig): SessionReplayPipeline {
    const { recordPipeline, sessionBatchFactory, offsetManager, maxBatchSizeBytes, maxBatchAgeMs } = config

    return newAccumulatingPipeline<
        SessionReplayPipelineInput,
        SessionReplayPipelineOutput,
        { message: Message },
        { message: Message },
        SessionBatchContext,
        SessionBlockMetadata[],
        Record<string, never>,
        OverflowOutput
    >({
        beforeBatch: (builder) => builder.pipe(createCreateSessionBatchStep(sessionBatchFactory)),
        pipeline: recordPipeline,
        // The flush lifecycle: write to storage (retention and keys already resolved at record time),
        // commit the offsets it covers, then record the flush metrics from the write step's block metadata.
        flush: (builder) =>
            builder.sequentially((b) =>
                b.pipe(createWriteStep()).pipe(createCommitOffsetsStep(offsetManager)).pipe(createRecordMetricsStep())
            ),
        shouldFlush: (batchContext) => batchContext.sessionBatchRecorder.size >= maxBatchSizeBytes,
        maxBatchAgeMs,
    })
}
