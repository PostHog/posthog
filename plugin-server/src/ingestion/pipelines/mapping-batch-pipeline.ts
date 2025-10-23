import { BatchPipeline, BatchPipelineResultWithContext } from './batch-pipeline.interface'
import { FilterOkBatchPipeline, OkResultWithContext } from './filter-ok-batch-pipeline'

export type MappingFunction<TInput, TOutput, CInput, COutput> = (
    element: OkResultWithContext<TInput, CInput>
) => OkResultWithContext<TOutput, COutput>

export class MappingBatchPipeline<
    TInput,
    TIntermediate,
    TOutput,
    CInput,
    CIntermediate = CInput,
    COutput = CIntermediate,
> implements BatchPipeline<TInput, TOutput, CInput, COutput>
{
    constructor(
        private previousPipeline: FilterOkBatchPipeline<TInput, TIntermediate, CInput, CIntermediate>,
        private mappingFn: MappingFunction<TIntermediate, TOutput, CIntermediate, COutput>
    ) {}

    feed(elements: BatchPipelineResultWithContext<TInput, CInput>): void {
        this.previousPipeline.feed(elements)
    }

    async next(): Promise<BatchPipelineResultWithContext<TOutput, COutput> | null> {
        const previousResults = await this.previousPipeline.next()
        if (previousResults === null) {
            return null
        }
        return previousResults.map((element) => this.mappingFn(element))
    }
}
