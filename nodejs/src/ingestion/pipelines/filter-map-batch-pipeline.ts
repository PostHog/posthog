import { BatchPipeline, BatchPipelineResultWithContext } from './batch-pipeline.interface'
import { PipelineContext, PipelineResultWithContext } from './pipeline.interface'
import { PipelineResultOk, isOkResult } from './results'

export type OkResultWithContext<TOutput, COutput> = {
    result: PipelineResultOk<TOutput>
    context: PipelineContext<COutput>
}

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
> implements BatchPipeline<TInput, TOutput, CInput, COutput | CIntermediate>
{
    constructor(
        private previousPipeline: BatchPipeline<TInput, TIntermediate, CInput, CIntermediate>,
        private mappingFn: FilterMapMappingFunction<TIntermediate, TMapped, CIntermediate, CMapped>,
        private subPipeline: BatchPipeline<TMapped, TOutput, CMapped, COutput>
    ) {}

    feed(elements: BatchPipelineResultWithContext<TInput, CInput>): void {
        this.previousPipeline.feed(elements)
    }

    async next(): Promise<BatchPipelineResultWithContext<TOutput, COutput | CIntermediate> | null> {
        // Try subpipeline first (drains any pending results)
        const subPipelineResults = await this.subPipeline.next()
        if (subPipelineResults !== null) {
            return subPipelineResults
        }

        // Get results from previous pipeline
        const previousResults = await this.previousPipeline.next()
        if (previousResults === null) {
            return null
        }

        // Separate OK and non-OK results
        const okResults: OkResultWithContext<TIntermediate, CIntermediate>[] = []
        const nonOkResults: PipelineResultWithContext<TOutput, CIntermediate>[] = []

        for (const element of previousResults) {
            if (isOkResult(element.result)) {
                okResults.push({
                    result: element.result,
                    context: element.context,
                })
            } else {
                nonOkResults.push({
                    result: element.result,
                    context: element.context,
                })
            }
        }

        // Map OK results and feed to subpipeline
        if (okResults.length > 0) {
            const mappedResults: BatchPipelineResultWithContext<TMapped, CMapped> = okResults.map((element) =>
                this.mappingFn(element)
            )
            this.subPipeline.feed(mappedResults)
        }

        // Return non-OK results immediately if any
        if (nonOkResults.length > 0) {
            return nonOkResults
        }

        // No OK results were fed to subpipeline, return empty batch
        if (okResults.length === 0) {
            return []
        }

        return this.subPipeline.next()
    }
}
