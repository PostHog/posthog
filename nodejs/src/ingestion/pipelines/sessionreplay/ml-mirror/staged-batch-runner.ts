import { Message } from 'node-rdkafka'

import { PromiseScheduler } from '~/common/utils/promise-scheduler'
import { BatchingContext, BatchingPipeline } from '~/ingestion/framework/batching-pipeline'
import { ChunkPipelineResultWithContext } from '~/ingestion/framework/chunk-pipeline.interface'
import { createBatch } from '~/ingestion/framework/helpers'
import { OkResultWithContext } from '~/ingestion/framework/pipeline.interface'
import { isOkResult } from '~/ingestion/framework/results'
import { SessionReplayPipelineConfig } from '~/ingestion/pipelines/sessionreplay'
import { AdmittedBatch } from '~/ingestion/pipelines/sessionreplay/batch-stages'
import { BatchCommitter, StagedBatchRunner } from '~/ingestion/pipelines/sessionreplay/staged-batch'

import {
    MlAnonymizePipeline,
    MlMirrorCollection,
    MlMirrorImageScrubProducer,
    MlMirrorPipelineOptions,
    MlMirrorUrlFetchProducer,
    MlPreparePipeline,
    createMlMirrorAnonymizePipeline,
    createMlMirrorPreparePipeline,
} from './ml-mirror-pipeline'

/** The three stages a poll batch passes through, in order. Only anonymize is CPU work; the other two wait on DynamoDB, KMS, Redis, Kafka and S3. */
export const ML_BATCH_STAGES = ['prepare', 'anonymize', 'commit'] as const

/**
 * Runs each poll batch through the prepare, anonymize and commit stages the ingester admitted it to, so
 * the I/O-bound prepare and commit stages of neighbouring batches overlap the CPU-bound anonymize stage
 * of this one. Offsets and lag are tracked in the commit stage, in batch order, as before.
 */
export class MlMirrorStagedBatchRunner implements StagedBatchRunner {
    public readonly stages = ML_BATCH_STAGES
    private pipelines?: { prepare: MlPreparePipeline; anonymize: MlAnonymizePipeline; scheduler: PromiseScheduler }

    constructor(
        private readonly mlOptions: MlMirrorPipelineOptions,
        private readonly imageScrub?: MlMirrorImageScrubProducer,
        private readonly collection?: MlMirrorCollection,
        private readonly urlFetch?: MlMirrorUrlFetchProducer
    ) {}

    public start(config: SessionReplayPipelineConfig): void {
        this.pipelines = {
            prepare: createMlMirrorPreparePipeline(config, this.mlOptions),
            anonymize: createMlMirrorAnonymizePipeline(
                config,
                this.mlOptions,
                this.imageScrub,
                this.collection,
                this.urlFetch
            ),
            scheduler: config.promiseScheduler,
        }
    }

    public run(messages: Message[], batch: AdmittedBatch<void>, committer: BatchCommitter): Promise<void> {
        if (!this.pipelines) {
            return Promise.reject(new Error('ML mirror staged batch runner used before start'))
        }
        const { prepare, anonymize, scheduler } = this.pipelines
        return batch
            .stage('prepare', async () => {
                if (!messages.length) {
                    return { survivors: [], maxOffsets: new Map<number, number>(), handle: null }
                }
                const retentions = {
                    getRetention: (teamId: number, sessionId: string) => committer.knownRetention(teamId, sessionId),
                }
                const fed = createBatch(messages.map((message) => ({ message, sessionBatchRecorder: retentions })))
                const { elements, batchContext } = await drainBatch(prepare, fed, scheduler)
                // The offsets are taken here so the dropped messages, which are most of them on this lane, do not keep their Kafka buffers alive through the scrub.
                return {
                    survivors: elements.flatMap(({ result }) => (isOkResult(result) ? [result.value] : [])),
                    maxOffsets: maxOffsetsOf(elements),
                    handle: batchContext.mlBatch,
                }
            })
            .stage('anonymize', async ({ survivors, maxOffsets, handle }) => {
                if (survivors.length) {
                    await drainBatch(anonymize, createBatch(survivors), scheduler)
                }
                return { maxOffsets, handle }
            })
            .stage('commit', ({ maxOffsets, handle }) =>
                committer.commit(async (recorder, isAssigned) => {
                    const okMessages = handle ? await handle.commit(recorder, scheduler, isAssigned) : []
                    return {
                        maxOffsets: new Map([...maxOffsets].filter(([partition]) => isAssigned(partition))),
                        okMessages,
                    }
                })
            )
            .done()
    }
}

type StageElements<TOutput, COutput extends BatchingContext, R extends string> = ChunkPipelineResultWithContext<
    TOutput,
    COutput,
    R
>

// Each stage pipeline holds one batch at a time and the runner feeds each stage in batch order, so draining to null returns exactly the batch just fed.
async function drainBatch<TInput, TOutput, CInput, CBatch, COutput extends BatchingContext, R extends string>(
    pipeline: BatchingPipeline<TInput, TOutput, CInput, CBatch, COutput, R>,
    batch: OkResultWithContext<TInput, CInput>[],
    promiseScheduler: PromiseScheduler
): Promise<{ elements: StageElements<TOutput, COutput, R>; batchContext: CBatch }> {
    const feedResult = await pipeline.feed(batch, {})
    if (!feedResult.ok) {
        throw new Error(`ML mirror stage rejected feed: ${feedResult.kind} (${feedResult.reason})`)
    }
    let drained: { elements: StageElements<TOutput, COutput, R>; batchContext: CBatch } | undefined
    let batchResult = await pipeline.next()
    while (batchResult !== null) {
        for (const sideEffect of batchResult.sideEffects ?? []) {
            void promiseScheduler.schedule(sideEffect)
        }
        if (drained) {
            throw new Error('ML mirror stage drained a second batch, so the first batch would lose its messages')
        }
        drained = { elements: batchResult.elements, batchContext: batchResult.batchContext }
        batchResult = await pipeline.next()
    }
    if (!drained) {
        throw new Error('ML mirror stage returned no batch, which a feed of no elements also causes')
    }
    return drained
}

// Every message reaches a terminal result in the prepare stage or later, and every disposition advances the offset, so the prepare elements carry every offset of the batch.
function maxOffsetsOf<R extends string>(
    prepared: ChunkPipelineResultWithContext<unknown, { message: Message }, R>
): Map<number, number> {
    const maxOffsets = new Map<number, number>()
    for (const { context } of prepared) {
        const { partition, offset } = context.message
        const current = maxOffsets.get(partition)
        if (current === undefined || offset > current) {
            maxOffsets.set(partition, offset)
        }
    }
    return maxOffsets
}
