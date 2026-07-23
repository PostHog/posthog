import { Message } from 'node-rdkafka'

import { DlqOutput, IngestionWarningsOutput, OverflowOutput } from '~/common/outputs'
import { IngestionOutputs } from '~/common/outputs/ingestion-outputs'
import { EventIngestionRestrictionManager } from '~/common/utils/event-ingestion-restrictions'
import { PromiseScheduler } from '~/common/utils/promise-scheduler'
import { createApplyEventRestrictionsStep, createParseHeadersStep } from '~/ingestion/common/steps/event-preprocessing'
import { IngestionOverflowMode } from '~/ingestion/config'
import { BatchingContext, BatchingPipeline } from '~/ingestion/framework/batching-pipeline'
import { newBatchingPipeline } from '~/ingestion/framework/builders'
import { TopHogRegistry, createTopHogWrapper, sum, timer } from '~/ingestion/framework/extensions/tophog'
import { createBatch } from '~/ingestion/framework/helpers'
import { PipelineConfig } from '~/ingestion/framework/result-handling-pipeline'
import { isOkResult, ok } from '~/ingestion/framework/results'
import { ParsedMessageData } from '~/ingestion/pipelines/sessionreplay/kafka/types'
import { SessionBatchRecorder } from '~/ingestion/pipelines/sessionreplay/sessions/session-batch-recorder'
import { SessionFilter } from '~/ingestion/pipelines/sessionreplay/sessions/session-filter'
import { SessionTracker } from '~/ingestion/pipelines/sessionreplay/sessions/session-tracker'
import { RetentionService } from '~/ingestion/pipelines/sessionreplay/shared/retention/retention-service'
import { TeamService } from '~/ingestion/pipelines/sessionreplay/shared/teams/team-service'
import { KeyStore } from '~/ingestion/pipelines/sessionreplay/shared/types'
import { TeamForReplay } from '~/ingestion/pipelines/sessionreplay/teams/types'
import { ValueMatcher } from '~/types'

import { createLibVersionMonitorStep } from './lib-version-monitor-step'
import { createParseMessageStep } from './parse-message-step'
import { MessageContext } from './pipeline-types'
import { createRecordSessionEventStep } from './record-session-event-step'
import { SessionBatchContext } from './session-batch-context'
import { createMarkSeenStep } from './session-batch-mark-seen-step'
import { createResolveRetentionStep } from './session-batch-resolve-retention-step'
import { createTrackAndGateStep } from './session-batch-track-and-gate-step'
import { createResolveKeyStep } from './session-resolve-key-step'
import { createTeamFilterStep } from './team-filter-step'
import { createValidateSessionReplayHeadersStep } from './validate-headers-step'

export interface SessionReplayPipelineInput extends SessionBatchContext {
    message: Message
}

export interface SessionReplayPipelineOutput {
    team: TeamForReplay
    parsedMessage: ParsedMessageData
}

/**
 * The session replay pipeline: a batching pipeline whose input elements each carry the session batch
 * recorder they fold into ({@link SessionBatchContext}). The layer above (the consumer, later the
 * accumulating pipeline) owns the recorder and stamps it on the messages it feeds, so the steps stay
 * decoupled from batch creation and flushing.
 */
export type SessionReplayPipeline = BatchingPipeline<
    SessionReplayPipelineInput,
    SessionReplayPipelineOutput,
    MessageContext,
    Record<never, object>,
    MessageContext & BatchingContext,
    OverflowOutput
>

export interface SessionReplayPipelineConfig {
    outputs: IngestionOutputs<IngestionWarningsOutput | DlqOutput | OverflowOutput>
    eventIngestionRestrictionManager: EventIngestionRestrictionManager
    overflowMode: IngestionOverflowMode
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

/**
 * Creates the session replay pipeline.
 *
 * Each feed() is one batch: every element already carries the recorder it folds into (stamped by the
 * layer above), and the per-message sub-pipeline processes messages through these phases:
 * 1. Restrictions - Parse headers and apply event ingestion restrictions (drop/overflow)
 * 2. Team Filter - Validate team ownership and enrich with team context
 * 3. Parse - Parse Kafka messages into structured session recording data (inside teamAware for warning handling)
 * 4. Version Monitor - Check library version and emit warnings for old versions
 * 5. Record - Record parsed messages to the batch's recorder
 */
export function createSessionReplayPipeline(config: SessionReplayPipelineConfig): SessionReplayPipeline {
    const {
        outputs,
        eventIngestionRestrictionManager,
        overflowMode,
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

    return newBatchingPipeline<
        SessionReplayPipelineInput,
        SessionReplayPipelineOutput,
        MessageContext,
        Record<never, object>,
        MessageContext,
        OverflowOutput
    >(
        (beforeBatch) =>
            beforeBatch.pipe(function passThroughBeforeBatch(input) {
                return Promise.resolve(ok(input))
            }),
        (batch) =>
            batch
                .messageAware((b) =>
                    b
                        .sequentially((b) =>
                            b
                                // Parse headers and apply restrictions (drop/overflow)
                                .pipe(createParseHeadersStep())
                                .pipe(
                                    createApplyEventRestrictionsStep(eventIngestionRestrictionManager, {
                                        overflowMode,
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
                        .pipeChunk(createResolveRetentionStep(retentionService), {
                            retry: { tries: 3, sleepMs: 100 },
                        })
                        // Track sessions and rate-limit new ones for the whole batch, tagging the survivors with
                        // isNewSession and dropping the blocked ones right here (they carry no key, so nothing
                        // downstream acts on them). Its own retry scope means a later key-resolution failure never
                        // re-runs the rate limiter and double-charges the budget.
                        .pipeChunk(createTrackAndGateStep(sessionTracker, sessionFilter), {
                            retry: { tries: 3, sleepMs: 100 },
                        })
                        // Resolve each session's encryption key. Grouped by session so it runs once per session
                        // (the cached keystore fans the key to its other messages) and concurrently across
                        // sessions, capped to bound KMS/DynamoDB fan-out. Per-session retry isolates a transient
                        // keystore blip to that one session. Deleted sessions are dropped here.
                        .concurrentlyPerGroup(
                            (element) => `${element.team.teamId}:${element.headers.session_id}`,
                            (group) =>
                                group.sequentially((b) =>
                                    b.pipe(createResolveKeyStep(keyStore), {
                                        retry: { name: 'resolve_session_key', tries: 3, sleepMs: 100 },
                                    })
                                ),
                            { maxConcurrency: sessionKeyResolutionMaxConcurrency }
                        )
                        // Re-collect the per-session groups into one batch — both to mark the whole batch seen
                        // in a single Redis write and as the barrier that guarantees every key is resolved first.
                        .gather()
                        // Mark the surviving new sessions seen, now that every key is durably resolved.
                        .pipeChunk(createMarkSeenStep(sessionTracker))
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
                .gather(),
        (afterBatch) =>
            afterBatch.pipe(function passThroughAfterBatch(input) {
                return Promise.resolve(ok(input))
            }),
        // One batch in flight at a time (also the framework default): a feed's elements carry the
        // recorder current when it was fed, so a concurrent batch could span a flush and record into a
        // stale recorder.
        { concurrentBatches: 1 }
    )
}

/** The Kafka progress and lag inputs a processed batch yields for the caller to act on after it drains. */
export interface SessionReplayBatchProgress {
    /** Highest Kafka offset reached per partition, across every terminal result — advances the commit. */
    maxOffsets: Map<number, number>
    /** Source messages of the OK (recorded) results only, for ingestion-lag sampling after the flush. */
    okMessages: Message[]
}

/**
 * Runs a batch of messages through the session replay pipeline and returns the Kafka progress it made:
 * the highest offset reached per partition, plus the source messages of the OK results.
 *
 * Every message ends the pipeline with a terminal result — OK (recorded), DROP, DLQ, or REDIRECT —
 * and each result still carries its source message in the context. Draining them here and taking the
 * max offset per partition is the single place Kafka progress is tracked: the recorder no longer
 * tracks offsets while recording, and drop/dlq steps no longer have to remember to. The caller feeds
 * the returned offsets to the offset manager, which commits them on the next flush. Every disposition
 * advances the offset, but only OK results are collected for lag sampling — those are the messages
 * actually recorded, matching the per-event `record-ingestion-lag` step's ingested-only semantics.
 *
 * Relies on the pipeline draining the whole fed batch before it returns null, so every fed message
 * yields exactly one terminal result here.
 *
 * Element side effects (DLQ/overflow produces) are already scheduled inside the sub-pipeline, but
 * side effects returned by the batching pipeline's before/afterBatch hooks ride on each BatchResult.
 * They go onto the same scheduler here, so the consumer's pre-flush drain awaits them before any
 * offset commits — the hooks are pure today, but a driver must not silently drop them.
 */
export async function runSessionReplayPipeline(
    pipeline: SessionReplayPipeline,
    messages: Message[],
    sessionBatchRecorder: SessionBatchRecorder,
    promiseScheduler: PromiseScheduler
): Promise<SessionReplayBatchProgress> {
    const maxOffsets = new Map<number, number>()
    const okMessages: Message[] = []
    if (messages.length === 0) {
        return { maxOffsets, okMessages }
    }

    // Stamp the caller's current recorder onto every message, so the record step folds into the batch
    // the layer above owns for this cycle.
    const batch = createBatch(messages.map((message) => ({ message, sessionBatchRecorder })))
    // The consumer drains each batch fully before feeding the next and the hooks always succeed,
    // so a rejected feed can only be a framework invariant violation.
    const feedResult = await pipeline.feed(batch)
    if (!feedResult.ok) {
        throw new Error(`session replay pipeline rejected feed: ${feedResult.kind} (${feedResult.reason})`)
    }

    let batchResult = await pipeline.next()
    while (batchResult !== null) {
        for (const sideEffect of batchResult.sideEffects ?? []) {
            void promiseScheduler.schedule(sideEffect)
        }
        for (const { result, context } of batchResult.elements) {
            const { partition, offset } = context.message
            const current = maxOffsets.get(partition)
            if (current === undefined || offset > current) {
                maxOffsets.set(partition, offset)
            }
            if (isOkResult(result)) {
                okMessages.push(context.message)
            }
        }
        batchResult = await pipeline.next()
    }

    return { maxOffsets, okMessages }
}
