/** The primary session replay inner pipeline plus an AI-training opt-in filter and an anonymize step. */
import { Message } from 'node-rdkafka'

import { OverflowOutput } from '~/common/outputs'
import { createApplyEventRestrictionsStep, createParseHeadersStep } from '~/ingestion/common/steps/event-preprocessing'
import { AccumulationContext } from '~/ingestion/framework/accumulating-pipeline'
import { ChunkPipelineBuilder, newChunkPipelineBuilder } from '~/ingestion/framework/builders'
import { createTopHogWrapper, sum, timer } from '~/ingestion/framework/extensions/tophog'
import { PipelineConfig, ResultHandlingPipeline } from '~/ingestion/framework/result-handling-pipeline'
import {
    SessionReplayInnerPipeline,
    SessionReplayInnerPipelineConfig,
    SessionReplayPipelineInput,
} from '~/ingestion/pipelines/sessionreplay'
import { createAiTrainingOptInFilterStep } from '~/ingestion/pipelines/sessionreplay/ai-training-optin-filter-step'
import { createParseAndAnonymizeMessageStep } from '~/ingestion/pipelines/sessionreplay/parse-and-anonymize-step'
import { createRecordSessionEventStep } from '~/ingestion/pipelines/sessionreplay/record-session-event-step'
import { SessionBatchContext } from '~/ingestion/pipelines/sessionreplay/session-batch-context'
import { createMarkSeenStep } from '~/ingestion/pipelines/sessionreplay/session-batch-mark-seen-step'
import { createResolveRetentionStep } from '~/ingestion/pipelines/sessionreplay/session-batch-resolve-retention-step'
import { createTrackAndGateStep } from '~/ingestion/pipelines/sessionreplay/session-batch-track-and-gate-step'
import { createResolveKeyStep } from '~/ingestion/pipelines/sessionreplay/session-resolve-key-step'
import { createTeamFilterStep } from '~/ingestion/pipelines/sessionreplay/team-filter-step'
import { createValidateSessionReplayHeadersStep } from '~/ingestion/pipelines/sessionreplay/validate-headers-step'

export function createMlMirrorReplayPipeline(config: SessionReplayInnerPipelineConfig): SessionReplayInnerPipeline {
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

    const pipelineConfig: PipelineConfig<OverflowOutput> = { outputs, promiseScheduler }
    const topHogWrapper = createTopHogWrapper(topHog)

    const processed = newChunkPipelineBuilder<
        SessionReplayPipelineInput & SessionBatchContext & AccumulationContext,
        { message: Message }
    >()
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
                // Mirror only data from orgs that opted into AI training.
                .pipe(createAiTrainingOptInFilterStep())
        )
        // Resolve retention up front (before parse), keyed on the (validated) session_id
        // header; drop unresolvable sessions.
        .gather()
        .pipeChunk(createResolveRetentionStep(retentionService), {
            retry: { tries: 3, sleepMs: 100 },
        })
        // Track sessions and rate-limit new ones for the whole batch, tagging the survivors with
        // isNewSession and dropping the blocked ones right here, in this step's own retry scope.
        .pipeChunk(createTrackAndGateStep(sessionTracker, sessionFilter), {
            retry: { tries: 3, sleepMs: 100 },
        })
        // Resolve each session's encryption key once per session (grouped), concurrently across
        // sessions with a bounded fan-out and per-session retry. Deleted sessions drop here.
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
                                    // The native Rust addon fuses parse+anonymize in one step.
                                    .pipe(
                                        topHogWrapper(createParseAndAnonymizeMessageStep(), [
                                            timer('parse_time_ms_by_session_id', (input) => ({
                                                token: input.headers.token ?? 'unknown',
                                                session_id: input.headers.session_id ?? 'unknown',
                                            })),
                                        ])
                                    )
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

    // Route non-OK results (DLQ/overflow/drop) into produce side effects, but do NOT schedule
    // them — leave them on each result's context so the accumulating pipeline can lift and surface
    // them. The builder's handleResults() forces handleSideEffects (which would consume them), so
    // wrap the result handler directly.
    return new ChunkPipelineBuilder(new ResultHandlingPipeline(processed.build(), pipelineConfig)).gather().build()
}
