import { Message } from 'node-rdkafka'

import { DlqOutput, IngestionWarningsOutput, OverflowOutput } from '~/common/outputs'
import { IngestionOutputs } from '~/common/outputs/ingestion-outputs'
import { EventIngestionRestrictionManager } from '~/common/utils/event-ingestion-restrictions'
import { PromiseScheduler } from '~/common/utils/promise-scheduler'
import { createApplyEventRestrictionsStep, createParseHeadersStep } from '~/ingestion/common/steps/event-preprocessing'
import { IngestionOverflowMode } from '~/ingestion/config'
import { BatchPipeline } from '~/ingestion/framework/batch-pipeline.interface'
import { newBatchPipelineBuilder } from '~/ingestion/framework/builders'
import { TopHogRegistry, createTopHogWrapper, sum, timer } from '~/ingestion/framework/extensions/tophog'
import { createBatch } from '~/ingestion/framework/helpers'
import { PipelineConfig } from '~/ingestion/framework/result-handling-pipeline'
import { ParsedMessageData } from '~/ingestion/pipelines/sessionreplay/kafka/types'
import { SessionBatchManager } from '~/ingestion/pipelines/sessionreplay/sessions/session-batch-manager'
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
import { createMarkSeenStep } from './session-batch-mark-seen-step'
import { createResolveRetentionStep } from './session-batch-resolve-retention-step'
import { createTrackAndGateStep } from './session-batch-track-and-gate-step'
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
    /** Session batch manager for recording sessions. */
    sessionBatchManager: SessionBatchManager
    /** Debug logging matcher for partition-based debugging. */
    isDebugLoggingEnabled: ValueMatcher<number>
}

/**
 * Creates the session replay pipeline.
 *
 * The pipeline processes messages through these phases:
 * 1. Restrictions - Parse headers and apply event ingestion restrictions (drop/overflow)
 * 2. Team Filter - Validate team ownership and enrich with team context
 * 3. Parse - Parse Kafka messages into structured session recording data (inside teamAware for warning handling)
 * 4. Version Monitor - Check library version and emit warnings for old versions
 * 5. Record - Record parsed messages to session batches
 */
export function createSessionReplayPipeline(
    config: SessionReplayPipelineConfig
): BatchPipeline<
    SessionReplayPipelineInput,
    SessionReplayPipelineOutput,
    MessageContext,
    MessageContext,
    OverflowOutput
> {
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
        sessionBatchManager,
        isDebugLoggingEnabled,
    } = config

    const pipelineConfig: PipelineConfig<OverflowOutput> = {
        outputs,
        promiseScheduler,
    }

    const topHogWrapper = createTopHogWrapper(topHog)

    const pipeline = newBatchPipelineBuilder<SessionReplayPipelineInput, MessageContext>()
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
                .pipeBatch(createResolveRetentionStep(retentionService, sessionBatchManager), {
                    retry: { tries: 3, sleepMs: 100 },
                })
                // Track sessions and rate-limit new ones for the whole batch, tagging the survivors with
                // isNewSession and dropping the blocked ones right here (they carry no key, so nothing
                // downstream acts on them). Its own retry scope means a later key-resolution failure never
                // re-runs the rate limiter and double-charges the budget.
                .pipeBatch(createTrackAndGateStep(sessionTracker, sessionFilter), {
                    retry: { tries: 3, sleepMs: 100 },
                })
                // Resolve each session's encryption key. Grouped by session so it runs once per session
                // (the cached keystore fans the key to its other messages) and concurrently across
                // sessions, capped to bound KMS/DynamoDB fan-out. Per-session retry isolates a transient
                // keystore blip to that one session. Deleted sessions are dropped here.
                .concurrentlyPerGroup(
                    (element) => `${element.team.teamId}:${element.headers.session_id}`,
                    (b) =>
                        b.pipe(createResolveKeyStep(keyStore), {
                            retry: { name: 'resolve_session_key', tries: 3, sleepMs: 100 },
                        }),
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
                                            .pipe(
                                                topHogWrapper(
                                                    createRecordSessionEventStep({
                                                        sessionBatchManager,
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
 * Runs a batch of messages through the session replay pipeline and returns the highest Kafka offset
 * reached per partition.
 *
 * Every message ends the pipeline with a terminal result — OK (recorded), DROP, DLQ, or REDIRECT —
 * and each result still carries its source message in the context. Draining them here and taking the
 * max offset per partition is the single place Kafka progress is tracked: the recorder no longer
 * tracks offsets while recording, and drop/dlq steps no longer have to remember to. The caller feeds
 * the returned offsets to the offset manager, which commits them on the next flush.
 *
 * Relies on the pipeline draining the whole fed batch before it returns null, so every fed message
 * yields exactly one terminal result here.
 */
export async function runSessionReplayPipeline(
    pipeline: BatchPipeline<
        SessionReplayPipelineInput,
        SessionReplayPipelineOutput,
        { message: Message },
        { message: Message },
        OverflowOutput
    >,
    messages: Message[]
): Promise<Map<number, number>> {
    const maxOffsetByPartition = new Map<number, number>()
    if (messages.length === 0) {
        return maxOffsetByPartition
    }

    const batch = createBatch(messages.map((message) => ({ message })))
    pipeline.feed(batch)

    let results = await pipeline.next()
    while (results !== null) {
        for (const { context } of results) {
            const { partition, offset } = context.message
            const current = maxOffsetByPartition.get(partition)
            if (current === undefined || offset > current) {
                maxOffsetByPartition.set(partition, offset)
            }
        }
        results = await pipeline.next()
    }

    return maxOffsetByPartition
}
