import { BatchPipeline, BatchPipelineResultWithContext, OkResultWithContext } from './batch-pipeline.interface'
import { Pipeline, PipelineResultWithContext } from './pipeline.interface'
import { isOkResult } from './results'

export class SequentialBatchPipeline<
    TInput,
    TIntermediate,
    TOutput,
    CInput,
    COutput = CInput,
    RPrev extends string = never,
    RStep extends string = never,
> implements BatchPipeline<TInput, TOutput, CInput, COutput, RPrev | RStep>
{
    constructor(
        private currentPipeline: Pipeline<TIntermediate, TOutput, COutput, RStep>,
        private previousPipeline: BatchPipeline<TInput, TIntermediate, CInput, COutput, RPrev>
    ) {}

    feed(elements: OkResultWithContext<TInput, CInput>[]): void {
        this.previousPipeline.feed(elements)
    }

    async next(): Promise<BatchPipelineResultWithContext<TOutput, COutput, RPrev | RStep> | null> {
        const previousResults = await this.previousPipeline.next()
        if (previousResults === null) {
            return null
        }

        const results: PipelineResultWithContext<TOutput, COutput, RPrev | RStep>[] = []
        for (const resultWithContext of previousResults) {
            if (isOkResult(resultWithContext.result)) {
                const pipelineResult = await this.currentPipeline.process({
                    result: resultWithContext.result,
                    context: resultWithContext.context,
                })
                results.push(pipelineResult)
            } else {
                results.push({
                    result: resultWithContext.result,
                    context: resultWithContext.context,
                })
            }
        }

        return results
    }
}
