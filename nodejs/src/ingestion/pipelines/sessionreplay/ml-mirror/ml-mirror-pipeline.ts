/** The primary session replay pipeline plus an AI-training opt-in filter and an anonymize step. */
import { OverflowOutput } from '~/common/outputs'
import { createApplyEventRestrictionsStep, createParseHeadersStep } from '~/ingestion/common/steps/event-preprocessing'
import { newBatchingPipeline } from '~/ingestion/framework/builders'
import { createTopHogWrapper, sum, timer } from '~/ingestion/framework/extensions/tophog'
import { PipelineConfig } from '~/ingestion/framework/result-handling-pipeline'
import { ok } from '~/ingestion/framework/results'
import {
    SessionReplayPipeline,
    SessionReplayPipelineConfig,
    SessionReplayPipelineInput,
    SessionReplayPipelineOutput,
} from '~/ingestion/pipelines/sessionreplay'
import { createAdmitSessionStep } from '~/ingestion/pipelines/sessionreplay/admit-session-step'
import { createAiTrainingOptInFilterStep } from '~/ingestion/pipelines/sessionreplay/ai-training-optin-filter-step'
import { createExtractConsoleLogsStep } from '~/ingestion/pipelines/sessionreplay/extract-console-logs-step'
import { createExtractSessionDataStep } from '~/ingestion/pipelines/sessionreplay/extract-session-data-step'
import { createParseAndAnonymizeMessageStep } from '~/ingestion/pipelines/sessionreplay/parse-and-anonymize-step'
import { MessageContext } from '~/ingestion/pipelines/sessionreplay/pipeline-types'
import { createRecordSessionDataStep } from '~/ingestion/pipelines/sessionreplay/record-session-data-step'
import { createRecordSessionFeaturesStep } from '~/ingestion/pipelines/sessionreplay/record-session-features-step'
import { createRecordSessionLogsStep } from '~/ingestion/pipelines/sessionreplay/record-session-logs-step'
import { createMarkSeenStep } from '~/ingestion/pipelines/sessionreplay/session-batch-mark-seen-step'
import { createResolveRetentionStep } from '~/ingestion/pipelines/sessionreplay/session-batch-resolve-retention-step'
import { createTrackAndGateStep } from '~/ingestion/pipelines/sessionreplay/session-batch-track-and-gate-step'
import { createResolveKeyStep } from '~/ingestion/pipelines/sessionreplay/session-resolve-key-step'
import { createTeamFilterStep } from '~/ingestion/pipelines/sessionreplay/team-filter-step'
import { createValidateSessionReplayHeadersStep } from '~/ingestion/pipelines/sessionreplay/validate-headers-step'

export function createMlMirrorReplayPipeline(config: SessionReplayPipelineConfig): SessionReplayPipeline {
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
                                .pipe(createParseHeadersStep())
                                .pipe(
                                    createApplyEventRestrictionsStep(eventIngestionRestrictionManager, {
                                        overflowMode,
                                        preservePartitionLocality: true,
                                    })
                                )
                                .pipe(createValidateSessionReplayHeadersStep())
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
                        // Track sessions and rate-limit new ones for the whole batch, tagging each with
                        // isNewSession and a gate verdict; blocked sessions are carried (not dropped) to the
                        // mark-seen step, all in this step's own retry scope.
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
                                            .sequentially((b) => {
                                                // The native Rust addon fuses parse+anonymize in one step.
                                                const parsed = b.pipe(
                                                    topHogWrapper(createParseAndAnonymizeMessageStep(), [
                                                        timer('parse_time_ms_by_session_id', (input) => ({
                                                            token: input.headers.token ?? 'unknown',
                                                            session_id: input.headers.session_id ?? 'unknown',
                                                        })),
                                                    ])
                                                )
                                                // Derive the per-message record data — the session
                                                // block chunks and the console logs — here, so the
                                                // record steps only aggregate. Extraction does the
                                                // per-message heavy lifting, so the per-session cost
                                                // metrics live on these two steps.
                                                return (
                                                    parsed
                                                        .pipe(
                                                            topHogWrapper(createExtractSessionDataStep(), [
                                                                sum(
                                                                    'message_size_by_session_id',
                                                                    (input) => ({
                                                                        token: input.parsedMessage.token ?? 'unknown',
                                                                        session_id: input.parsedMessage.session_id,
                                                                    }),
                                                                    (input) => input.parsedMessage.metadata.rawSize
                                                                ),
                                                                timer(
                                                                    'extract_data_time_ms_by_session_id',
                                                                    (input) => ({
                                                                        token: input.parsedMessage.token ?? 'unknown',
                                                                        session_id: input.parsedMessage.session_id,
                                                                    })
                                                                ),
                                                            ])
                                                        )
                                                        .pipe(
                                                            topHogWrapper(createExtractConsoleLogsStep(), [
                                                                timer(
                                                                    'extract_logs_time_ms_by_session_id',
                                                                    (input) => ({
                                                                        token: input.parsedMessage.token ?? 'unknown',
                                                                        session_id: input.parsedMessage.session_id,
                                                                    })
                                                                ),
                                                            ])
                                                        )
                                                        // Admission gates the batch: rate-limited or
                                                        // inconsistent messages drop here, so the
                                                        // record steps below only fold admitted
                                                        // messages and can run in any order.
                                                        .pipe(
                                                            createAdmitSessionStep({
                                                                isDebugLoggingEnabled,
                                                            })
                                                        )
                                                        .pipe(createRecordSessionDataStep())
                                                        .pipe(createRecordSessionLogsStep())
                                                        .pipe(createRecordSessionFeaturesStep())
                                                )
                                            })
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
        // One batch in flight at a time (also the framework default): each feed tags the manager's
        // current recorder, so a concurrent batch could span a flush and record into a stale recorder.
        { concurrentBatches: 1 }
    )
}
