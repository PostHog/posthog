import { BatchPipeline, BatchPipelineResultWithContext } from './batch-pipeline.interface'
import { PipelineContext } from './pipeline.interface'
import { PipelineResultOk, isOkResult } from './results'

export type OkResultWithContext<TOutput, COutput> = {
    result: PipelineResultOk<TOutput>
    context: PipelineContext<COutput>
}

export class FilterOkBatchPipeline<TInput, TOutput, CInput = PipelineContext, COutput = CInput>
    implements BatchPipeline<TInput, TOutput, CInput, COutput>
{
    constructor(private previousPipeline: BatchPipeline<TInput, TOutput, CInput, COutput>) {}

    feed(elements: BatchPipelineResultWithContext<TInput, CInput>): void {
        this.previousPipeline.feed(elements)
    }

    async next(): Promise<OkResultWithContext<TOutput, COutput>[] | null> {
        const previousResults = await this.previousPipeline.next()
        if (previousResults === null) {
            return null
        }

        const okResults: OkResultWithContext<TOutput, COutput>[] = []
        for (const element of previousResults) {
            if (isOkResult(element.result)) {
                okResults.push({
                    result: element.result,
                    context: element.context,
                })
            }
        }

        return okResults.length > 0 ? okResults : null
    }
}
