/** The primary session replay pipeline plus an AI-training opt-in filter and an anonymize step. */
import { Message } from 'node-rdkafka'

import { OverflowOutput } from '~/common/outputs'
import { createApplyEventRestrictionsStep, createParseHeadersStep } from '~/ingestion/common/steps/event-preprocessing'
import { BatchPipeline } from '~/ingestion/framework/batch-pipeline.interface'
import { newBatchPipelineBuilder } from '~/ingestion/framework/builders'
import { createTopHogWrapper, sum, timer } from '~/ingestion/framework/extensions/tophog'
import { PipelineConfig } from '~/ingestion/framework/result-handling-pipeline'
import {
    SessionReplayPipelineConfig,
    SessionReplayPipelineInput,
    SessionReplayPipelineOutput,
} from '~/ingestion/pipelines/sessionreplay'
import { createAiTrainingOptInFilterStep } from '~/ingestion/pipelines/sessionreplay/ai-training-optin-filter-step'
import { createAnonymizeStep } from '~/ingestion/pipelines/sessionreplay/anonymize-step'
import { ScrubContext } from '~/ingestion/pipelines/sessionreplay/anonymize/config'
import { createParseMessageStep } from '~/ingestion/pipelines/sessionreplay/parse-message-step'
import { createRecordSessionEventStep } from '~/ingestion/pipelines/sessionreplay/record-session-event-step'
import { createMarkSeenStep } from '~/ingestion/pipelines/sessionreplay/session-batch-mark-seen-step'
import { createResolveRetentionStep } from '~/ingestion/pipelines/sessionreplay/session-batch-resolve-retention-step'
import { createTrackAndGateStep } from '~/ingestion/pipelines/sessionreplay/session-batch-track-and-gate-step'
import { createResolveKeyStep } from '~/ingestion/pipelines/sessionreplay/session-resolve-key-step'
import { createTeamFilterStep } from '~/ingestion/pipelines/sessionreplay/team-filter-step'
import { createValidateSessionReplayHeadersStep } from '~/ingestion/pipelines/sessionreplay/validate-headers-step'

export type MlMirrorReplayPipelineConfig = SessionReplayPipelineConfig & {
    /** Shared, immutable scrub context (allow lists + tunables). */
    scrubContext: ScrubContext
}

export function createMlMirrorReplayPipeline(
    config: MlMirrorReplayPipelineConfig
): BatchPipeline<
    SessionReplayPipelineInput,
    SessionReplayPipelineOutput,
    { message: Message },
    { message: Message },
    OverflowOutput
> {
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
        sessionBatchManager,
        isDebugLoggingEnabled,
        scrubContext,
    } = config

    const pipelineConfig: PipelineConfig<OverflowOutput> = { outputs, promiseScheduler }
    const topHogWrapper = createTopHogWrapper(topHog)

    const pipeline = newBatchPipelineBuilder<SessionReplayPipelineInput, { message: Message }>()
        .messageAware((b) =>
            b
                .sequentially((b) =>
                    b
                        .pipe(createParseHeadersStep())
                        .pipe(
                            createApplyEventRestrictionsStep(eventIngestionRestrictionManager, {
                                overflowEnabled,
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
                .pipeBatchWithRetry(createResolveRetentionStep(retentionService, sessionBatchManager), {
                    tries: 3,
                    sleepMs: 100,
                })
                // Track sessions and rate-limit/block new ones for the whole batch, tagging each with
                // isNewSession; blocked sessions are dropped here, in their own retry scope.
                .pipeBatchWithRetry(createTrackAndGateStep(sessionTracker, sessionFilter), {
                    tries: 3,
                    sleepMs: 100,
                })
                // Resolve each session's encryption key once per session (grouped), concurrently across
                // sessions with a bounded fan-out and per-session retry. Deleted sessions drop here.
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
                                            .pipe(
                                                topHogWrapper(createParseMessageStep(), [
                                                    timer('parse_time_ms_by_session_id', (input) => ({
                                                        token: input.headers.token ?? 'unknown',
                                                        session_id: input.headers.session_id ?? 'unknown',
                                                    })),
                                                ])
                                            )
                                            // Anonymize before recording so derived metadata is scrubbed too.
                                            .pipe(createAnonymizeStep({ scrubContext }))
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
