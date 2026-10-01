/** The primary session replay pipeline plus an AI-training opt-in filter and an anonymize step, split into the stages the staged batch runner overlaps. */
import { OverflowOutput } from '~/common/outputs'
import { IngestionOutputs } from '~/common/outputs/ingestion-outputs'
import { BatchingContext, BatchingPipeline } from '~/ingestion/framework/batching-pipeline'
import { newBatchingPipeline } from '~/ingestion/framework/builders'
import { createTopHogWrapper, timer } from '~/ingestion/framework/extensions/tophog'
import { aggregateKafkaDebugContexts } from '~/ingestion/framework/helpers'
import { PipelineConfig } from '~/ingestion/framework/result-handling-pipeline'
import { drop, ok } from '~/ingestion/framework/results'
import { ProcessingStep } from '~/ingestion/framework/steps'
import { SessionReplayPipelineConfig, SessionReplayPipelineOutput } from '~/ingestion/pipelines/sessionreplay'
import { createAiTrainingOptInFilterStep } from '~/ingestion/pipelines/sessionreplay/ai-training-optin-filter-step'
import type { CrawlHistoryStore } from '~/ingestion/pipelines/sessionreplay/ml-mirror-image-fetch/crawl-history'
import { createProduceCollectedImagesStep } from '~/ingestion/pipelines/sessionreplay/ml-mirror/produce-collected-images-step'
import { createProduceCollectedUrlsStep } from '~/ingestion/pipelines/sessionreplay/ml-mirror/produce-collected-urls-step'
import { MessageContext, SessionReplayHeaders } from '~/ingestion/pipelines/sessionreplay/pipeline-types'
import { createRecordSessionEventStep } from '~/ingestion/pipelines/sessionreplay/record-session-event-step'
import { SessionBatchContext } from '~/ingestion/pipelines/sessionreplay/session-batch-context'
import {
    SessionReplayPreprocessingInput,
    addSessionReplayPreprocessing,
    addSessionReplaySessionResolution,
    withSessionReplayRecordingMetrics,
} from '~/ingestion/pipelines/sessionreplay/session-replay-pipeline-stages'
import { RetentionPeriod } from '~/ingestion/pipelines/sessionreplay/shared/constants'
import { MlImageFetchOutput, MlImageScrubOutput } from '~/ingestion/pipelines/sessionreplay/shared/outputs'
import { SessionKey } from '~/ingestion/pipelines/sessionreplay/shared/types'
import { TeamForReplay } from '~/ingestion/pipelines/sessionreplay/teams/types'

import { MlBatchHandle, MlDeferrableInput } from './batch-handle'
import { MlKeyBatchController } from './keys/batch-controller'
import { MlSessionKeys } from './keys/key-store'
import { createParseAndAnonymizeMessageStep } from './parse-and-anonymize-step'
import { mlSessionIdDropReason } from './session-identifier-format'

export interface MlMirrorPipelineOptions {
    /** Cap on sessions scrubbed concurrently; each in-flight scrub occupies a libuv threadpool thread. */
    anonymizeMaxConcurrency: number
    keyManager?: MlKeyBatchController
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

/** What the prepare stage is fed: the message and a retention lookup, never the recorder, which a flush replaces while the batch is in flight. */
export type MlPrepareInput = SessionReplayPreprocessingInput

/** What the prepare stage hands the anonymize stage: a validated, key-resolved message with its batch handle. */
export interface MlPreparedMessage extends MlPrepareInput {
    headers: SessionReplayHeaders
    team: TeamForReplay
    retentionPeriod: RetentionPeriod
    isNewSession: boolean
    status: 'allowed'
    sessionKey: SessionKey
    mlBatch: MlBatchHandle
    mlKeys?: MlSessionKeys
}

/** The batch handle also rides on the batch context, so the commit stage reaches it when no message survived. */
export interface MlBatchContext {
    mlBatch: MlBatchHandle
}

export type MlPreparePipeline = BatchingPipeline<
    MlPrepareInput,
    MlPreparedMessage,
    MessageContext,
    MlBatchContext,
    MessageContext & BatchingContext,
    OverflowOutput
>

export type MlAnonymizePipeline = BatchingPipeline<
    MlPreparedMessage,
    SessionReplayPipelineOutput,
    MessageContext,
    Record<never, object>,
    MessageContext & BatchingContext,
    OverflowOutput
>

function createMlSessionIdFilterStep<T extends { headers: SessionReplayHeaders }>(
    nowMs: () => number
): ProcessingStep<T, T> {
    return function filterMlSessionId(input) {
        const reason = mlSessionIdDropReason(input.headers.session_id, nowMs())
        return Promise.resolve(reason ? drop(reason) : ok(input))
    }
}

/**
 * The I/O-bound front of the lane: header parsing, the opt-in and session ID filters, the key bulk
 * read, retention, session tracking and key resolution. Nothing here needs the CPU for long, so the
 * runner lets it work on the next batch while the anonymize stage scrubs the current one.
 */
export function createMlMirrorPreparePipeline(
    config: SessionReplayPipelineConfig,
    mlOptions: MlMirrorPipelineOptions
): MlPreparePipeline {
    const { outputs, promiseScheduler } = config
    const pipelineConfig: PipelineConfig<OverflowOutput> = { outputs, promiseScheduler }

    return newBatchingPipeline<
        MlPrepareInput,
        MlPreparedMessage,
        MessageContext,
        MlBatchContext,
        MessageContext,
        OverflowOutput
    >(
        (beforeBatch) =>
            beforeBatch.pipe(function openMlBatch(input) {
                const batchContext: MlBatchContext & typeof input.batchContext = {
                    ...input.batchContext,
                    mlBatch: new MlBatchHandle(mlOptions.keyManager),
                }
                return Promise.resolve(ok({ ...input, batchContext }))
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
                            .pipeChunk(async function readMlKeyBatch(values) {
                                if (!values.length) {
                                    return []
                                }
                                // The batching pipeline merges the batch context into every element, which the preprocessing types do not carry.
                                const { mlBatch } = values[0] as unknown as MlBatchContext
                                if (mlOptions.keyManager) {
                                    mlBatch.keys = await mlOptions.keyManager.prepare(
                                        values.map((value) => ({
                                            teamId: value.team.teamId,
                                            sessionId: value.headers.session_id,
                                        }))
                                    )
                                }
                                return values.map((value) => ok({ ...value, mlBatch }))
                            }),
                        config
                    ).pipeChunk(function attachMlKeys(values) {
                        return Promise.resolve(
                            values.map((value) => {
                                const prepared: MlPreparedMessage = {
                                    ...value,
                                    mlKeys: value.mlBatch.keys?.get(value.team.teamId, value.headers.session_id),
                                }
                                return ok(prepared)
                            })
                        )
                    })
                )
                .handleResults(pipelineConfig)
                .handleSideEffects(promiseScheduler, { await: false })
                .gather(),
        (afterBatch) =>
            afterBatch.pipe(function passThroughAfterBatch(input) {
                return Promise.resolve(ok(input))
            }),
        { concurrentBatches: 1 },
        { aggregateDebugContexts: aggregateKafkaDebugContexts }
    )
}

/**
 * The CPU-bound middle of the lane: the fused parse and scrub in the Rust addon. The record and
 * produce steps that follow it are deferred onto the batch handle, so this stage touches neither the
 * recorder nor Kafka and the runner can hold it to one batch at a time without holding anything else.
 */
export function createMlMirrorAnonymizePipeline(
    config: SessionReplayPipelineConfig,
    mlOptions: MlMirrorPipelineOptions,
    imageScrub?: MlMirrorImageScrubProducer,
    collection?: MlMirrorCollection,
    urlFetch?: MlMirrorUrlFetchProducer
): MlAnonymizePipeline {
    const { outputs, promiseScheduler, topHog, isDebugLoggingEnabled } = config

    const pipelineConfig: PipelineConfig<OverflowOutput> = { outputs, promiseScheduler }
    const topHogWrapper = createTopHogWrapper(topHog)
    // The deferred step runs at commit time with the recorder current then, so it is typed on the full recorder while the element it is queued from only carries the retention lookup.
    function deferPublication<T extends MlDeferrableInput & { mlBatch: MlBatchHandle }>(
        step: ProcessingStep<T & SessionBatchContext, T & SessionBatchContext>
    ): ProcessingStep<T, T> {
        return (input) => input.mlBatch.defer(input, step)
    }
    // Only the recording step answers with its message, so the lane reports lag once per message and not once per deferred step.
    function deferRecording<T extends MlDeferrableInput & { mlBatch: MlBatchHandle }>(
        step: ProcessingStep<T & SessionBatchContext, T & SessionBatchContext>
    ): ProcessingStep<T, T> {
        return (input) => input.mlBatch.defer(input, step, true)
    }

    return newBatchingPipeline<
        MlPreparedMessage,
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
                    b.filterMap(
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
                                                                : undefined
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
                                                                  imageScrub.producedRefCacheMax
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
                                                              })
                                                          )
                                                      )
                                                    : withImagesProduced
                                                return withUrlsProduced.pipe(
                                                    deferRecording(
                                                        withSessionReplayRecordingMetrics(
                                                            topHog,
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
            afterBatch.pipe(function passThroughAfterBatch(input) {
                return Promise.resolve(ok(input))
            }),
        { concurrentBatches: 1 },
        { aggregateDebugContexts: aggregateKafkaDebugContexts }
    )
}
