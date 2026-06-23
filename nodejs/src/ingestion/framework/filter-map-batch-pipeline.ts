import { BatchPipeline, BatchPipelineResultWithContext } from './batch-pipeline.interface'
import { InterleavingBatchPipeline, PullOutcome } from './interleaving-batch-pipeline'
import { OkResultWithContext, PipelineResultWithContext } from './pipeline.interface'
import { isOkResult } from './results'

export type FilterMapMappingFunction<TInput, TOutput, CInput, COutput> = (
    element: OkResultWithContext<TInput, CInput>
) => OkResultWithContext<TOutput, COutput>

/**
 * A batch pipeline that:
 * 1. Filters OK results from the previous pipeline
 * 2. Applies a mapping function to transform both values and context
 * 3. Processes the mapped results through a subpipeline
 * 4. Passes through non-OK results unchanged (returned before subpipeline results)
 *
 * Non-OK results are returned immediately without buffering, which may break
 * ordering relative to OK results that go through the subpipeline.
 *
 * Failures poison the pipeline: if the upstream, the mapping function, or the
 * subpipeline throws, results already in flight still drain, then next() rejects
 * with that error permanently.
 *
 * Synchronization (pulling upstream, feeding the subpipeline, draining it, and
 * staying responsive to concurrent feeds so a parked subpipeline can't strand
 * newly fed input) is handled by {@link InterleavingBatchPipeline}. This class
 * only supplies the filter/map/route policy via the onSourcePull callback.
 */
export class FilterMapBatchPipeline<
    TInput,
    TIntermediate,
    TMapped,
    TOutput,
    CInput,
    CIntermediate = CInput,
    CMapped = CIntermediate,
    COutput = CMapped,
    RPrev extends string = never,
    RSub extends string = never,
> implements BatchPipeline<TInput, TOutput, CInput, COutput | CIntermediate, RPrev | RSub>
{
    private inner: InterleavingBatchPipeline<TInput, TOutput, CInput, COutput | CIntermediate, RPrev | RSub>

    constructor(
        private previousPipeline: BatchPipeline<TInput, TIntermediate, CInput, CIntermediate, RPrev>,
        private mappingFn: FilterMapMappingFunction<TIntermediate, TMapped, CIntermediate, CMapped>,
        private subPipeline: BatchPipeline<TMapped, TOutput, CMapped, COutput, RSub>
    ) {
        this.inner = new InterleavingBatchPipeline<TInput, TOutput, CInput, COutput | CIntermediate, RPrev | RSub>({
            onFeed: (elements) => this.previousPipeline.feed(elements),
            onSourcePull: () => this.pullAndRoute(),
            onProcessPull: () => this.subPipeline.next(),
        })
    }

    feed(elements: OkResultWithContext<TInput, CInput>[]): void {
        this.inner.feed(elements)
    }

    next(): Promise<BatchPipelineResultWithContext<TOutput, COutput | CIntermediate, RPrev | RSub> | null> {
        return this.inner.next()
    }

    /**
     * Pull one batch from the previous pipeline, feed mapped OK results into the
     * subpipeline, and report what to do next: emit non-OK (or empty) batches
     * immediately, drain the subpipeline for the OK results, or signal that the
     * previous pipeline is empty.
     */
    private async pullAndRoute(): Promise<PullOutcome<TOutput, COutput | CIntermediate, RPrev | RSub>> {
        const previousResults = await this.previousPipeline.next()
        if (previousResults === null) {
            return { kind: 'drained' }
        }

        const okResults: OkResultWithContext<TIntermediate, CIntermediate>[] = []
        const nonOkResults: PipelineResultWithContext<TOutput, CIntermediate, RPrev | RSub>[] = []

        for (const element of previousResults) {
            if (isOkResult(element.result)) {
                okResults.push({ result: element.result, context: element.context })
            } else {
                nonOkResults.push({ result: element.result, context: element.context })
            }
        }

        if (okResults.length > 0) {
            this.subPipeline.feed(okResults.map((element) => this.mappingFn(element)))
        }

        if (nonOkResults.length > 0) {
            return { kind: 'emit', batch: nonOkResults }
        }

        // A non-null empty batch surfaces as [] (a valid empty batch, distinct
        // from null = end of stream), matching the previous pipeline 1:1.
        if (okResults.length === 0) {
            return { kind: 'emit', batch: [] }
        }

        return { kind: 'drain' }
    }
}
