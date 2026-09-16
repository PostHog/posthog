/** The primary session replay pipeline plus an AI-training opt-in filter and an anonymize step. */
import { OverflowOutput } from '~/common/outputs'
import { IngestionOutputs } from '~/common/outputs/ingestion-outputs'
import { newBatchingPipeline } from '~/ingestion/framework/builders'
import { createTopHogWrapper, timer } from '~/ingestion/framework/extensions/tophog'
import { aggregateKafkaDebugContexts } from '~/ingestion/framework/helpers'
import { PipelineConfig } from '~/ingestion/framework/result-handling-pipeline'
import { drop, ok } from '~/ingestion/framework/results'
import { ProcessingStep } from '~/ingestion/framework/steps'
import {
    SessionReplayPipeline,
    SessionReplayPipelineConfig,
    SessionReplayPipelineInput,
    SessionReplayPipelineOutput,
} from '~/ingestion/pipelines/sessionreplay'
import { createAiTrainingOptInFilterStep } from '~/ingestion/pipelines/sessionreplay/ai-training-optin-filter-step'
import type { CrawlHistoryStore } from '~/ingestion/pipelines/sessionreplay/ml-mirror-image-fetch/crawl-history'
import { createProduceCollectedImagesStep } from '~/ingestion/pipelines/sessionreplay/ml-mirror/produce-collected-images-step'
import { createProduceCollectedUrlsStep } from '~/ingestion/pipelines/sessionreplay/ml-mirror/produce-collected-urls-step'
import { MessageContext, SessionReplayHeaders } from '~/ingestion/pipelines/sessionreplay/pipeline-types'
import { createRecordSessionEventStep } from '~/ingestion/pipelines/sessionreplay/record-session-event-step'
import { RecordSessionEventStepInput } from '~/ingestion/pipelines/sessionreplay/record-session-event-step'
import {
    addSessionReplayPreprocessing,
    addSessionReplaySessionResolution,
    withSessionReplayRecordingMetrics,
} from '~/ingestion/pipelines/sessionreplay/session-replay-pipeline-stages'
import { MlImageFetchOutput, MlImageScrubOutput } from '~/ingestion/pipelines/sessionreplay/shared/outputs'

import { createParseAndAnonymizeMessageStep } from './parse-and-anonymize-step'
import { MlPrivacyBatchController } from './privacy/batch-controller'
import { mlSessionIdDropReason } from './session-identifier-format'

export interface MlMirrorPipelineOptions {
    /** Cap on sessions scrubbed concurrently; each in-flight scrub occupies a libuv threadpool thread. */
    anonymizeMaxConcurrency: number
    privacy?: MlPrivacyBatchController
    nowMs?: () => number
}

/** Enables the image-collection lane: inlined images become refs, originals go to the scrub topic. */
export interface MlMirrorImageScrubProducer {
    outputs: IngestionOutputs<MlImageFetchOutput | MlImageScrubOutput>
    producedRefCacheMax: number
}

/** Enables the fetch lane's producer: collected URLs go to the fetch topic, keyed by the
 *  registrable domain of each URL. */
export interface MlMirrorUrlFetchProducer {
    outputs: IngestionOutputs<MlImageFetchOutput | MlImageScrubOutput>
    producedRefCacheMax: number
    producedRefCacheWindowMs: number
    crawlHistory?: Pick<CrawlHistoryStore, 'read'>
}

/**
 * Which collection lanes the anonymizer runs, and the key they derive their ref HMAC keys from.
 *
 * Separate from the two producer settings, because collecting and producing are separate
 * decisions. Collection alone measures. A produce puts original, unscrubbed URLs onto Kafka.
 *
 * The URL lane measures before any topic exists. A requirement to turn a producer on first would
 * make that measurement impossible to take on its own.
 */
export interface MlMirrorCollection {
    /** The root key for image content and URL HMAC keys. */
    pseudonymSecret: string | Buffer
    collectImages: boolean
    collectUrls: boolean
}

function createMlSessionIdFilterStep<T extends { headers: SessionReplayHeaders }>(
    nowMs: () => number
): ProcessingStep<T, T> {
    return function filterMlSessionId(input) {
        const reason = mlSessionIdDropReason(input.headers.session_id, nowMs())
        return Promise.resolve(reason ? drop(reason) : ok(input))
    }
}

export function createMlMirrorReplayPipeline(
    config: SessionReplayPipelineConfig,
    mlOptions: MlMirrorPipelineOptions,
    imageScrub?: MlMirrorImageScrubProducer,
    collection?: MlMirrorCollection,
    urlFetch?: MlMirrorUrlFetchProducer
): SessionReplayPipeline {
    const { outputs, promiseScheduler, topHog, isDebugLoggingEnabled } = config

    const pipelineConfig: PipelineConfig<OverflowOutput> = { outputs, promiseScheduler }
    const topHogWrapper = createTopHogWrapper(topHog)
    function deferPublication<T extends RecordSessionEventStepInput & { headers: { session_id: string } }>(
        step: ProcessingStep<T, T>
    ): ProcessingStep<T, T> {
        return mlOptions.privacy ? (input) => mlOptions.privacy!.defer(input, step) : step
    }

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
                mlOptions.privacy?.reset()
                return Promise.resolve(ok(input))
            }),
        (batch) =>
            batch
                .messageAware((b) =>
                    addSessionReplaySessionResolution(
                        b
                            .sequentially((b) =>
                                addSessionReplayPreprocessing(b, config)
                                    .pipe(createMlSessionIdFilterStep(mlOptions.nowMs ?? Date.now))
                                    // Mirror only data from orgs that opted into AI training.
                                    .pipe(createAiTrainingOptInFilterStep())
                            )
                            .gather()
                            .pipeChunk(async function readMlPrivacyBatch(values) {
                                if (mlOptions.privacy) {
                                    await mlOptions.privacy.prepare(
                                        values.map((value) => {
                                            if (!value.team.organizationId) {
                                                throw new Error('ML privacy requires organization ownership')
                                            }
                                            return {
                                                teamId: value.team.teamId,
                                                organizationId: value.team.organizationId,
                                                sessionId: value.headers.session_id,
                                            }
                                        })
                                    )
                                }
                                return values.map((value) => ok(value))
                            }),
                        config
                    ).filterMap(
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
                                        // Downstream consumers don't require event order within a
                                        // session's block, so scrubbing is free to complete out of order.
                                        .concurrently(
                                            (b) => {
                                                // The native Rust addon fuses parse+anonymize in one step.
                                                const parsed = b.pipe(
                                                    topHogWrapper(
                                                        createParseAndAnonymizeMessageStep(
                                                            collection?.collectImages || collection?.collectUrls
                                                                ? collection
                                                                : undefined,
                                                            mlOptions.privacy
                                                        ),
                                                        [
                                                            timer('parse_time_ms_by_session_id', (input) => ({
                                                                token: input.headers.token ?? 'unknown',
                                                                session_id: input.headers.session_id ?? 'unknown',
                                                            })),
                                                        ]
                                                    )
                                                )
                                                const withImagesProduced = imageScrub
                                                    ? parsed.pipe(
                                                          deferPublication(
                                                              createProduceCollectedImagesStep(
                                                                  imageScrub.outputs,
                                                                  imageScrub.producedRefCacheMax,
                                                                  mlOptions.privacy
                                                              )
                                                          )
                                                      )
                                                    : parsed
                                                const withUrlsProduced = urlFetch
                                                    ? withImagesProduced.pipe(
                                                          deferPublication(
                                                              createProduceCollectedUrlsStep(urlFetch.outputs, topHog, {
                                                                  producedRefCacheMax: urlFetch.producedRefCacheMax,
                                                                  producedRefCacheWindowMs:
                                                                      urlFetch.producedRefCacheWindowMs,
                                                                  crawlHistory: urlFetch.crawlHistory,
                                                                  privacy: mlOptions.privacy,
                                                              })
                                                          )
                                                      )
                                                    : withImagesProduced
                                                return withUrlsProduced.pipe(
                                                    withSessionReplayRecordingMetrics(
                                                        topHog,
                                                        deferPublication(
                                                            createRecordSessionEventStep({
                                                                isDebugLoggingEnabled,
                                                            })
                                                        )
                                                    )
                                                )
                                            },
                                            { maxConcurrency: mlOptions.anonymizeMaxConcurrency }
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
            afterBatch.pipe(async function passThroughAfterBatch(input) {
                await mlOptions.privacy?.commit(promiseScheduler)
                return ok(input)
            }),
        // One batch in flight at a time (also the framework default): each feed tags the manager's
        // current recorder, so a concurrent batch could span a flush and record into a stale recorder.
        { concurrentBatches: 1 },
        { aggregateDebugContexts: aggregateKafkaDebugContexts }
    )
}
