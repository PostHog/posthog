/** The primary session replay pipeline plus an AI-training opt-in filter and an anonymize step. */
import { Message } from 'node-rdkafka'

import { OverflowOutput } from '~/common/outputs'
import { createApplyEventRestrictionsStep, createParseHeadersStep } from '~/ingestion/common/steps/event-preprocessing'
import { BatchPipelineUnwrapper } from '~/ingestion/framework/batch-pipeline-unwrapper'
import { newBatchPipelineBuilder } from '~/ingestion/framework/builders'
import { createTopHogWrapper, sum, timer } from '~/ingestion/framework/extensions/tophog'
import { createUnwrapper } from '~/ingestion/framework/helpers'
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
import { createTeamFilterStep } from '~/ingestion/pipelines/sessionreplay/team-filter-step'

export type MlMirrorReplayPipelineConfig = SessionReplayPipelineConfig & {
    /** Shared, immutable scrub context (allow lists + tunables). */
    scrubContext: ScrubContext
}

export function createMlMirrorReplayPipeline(
    config: MlMirrorReplayPipelineConfig
): BatchPipelineUnwrapper<
    SessionReplayPipelineInput,
    SessionReplayPipelineOutput,
    { message: Message },
    OverflowOutput
> {
    const {
        outputs,
        eventIngestionRestrictionManager,
        overflowEnabled,
        promiseScheduler,
        teamService,
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
                        .pipe(createTeamFilterStep(teamService))
                        // Mirror only data from orgs that opted into AI training.
                        .pipe(createAiTrainingOptInFilterStep())
                )
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

    return createUnwrapper(pipeline)
}
