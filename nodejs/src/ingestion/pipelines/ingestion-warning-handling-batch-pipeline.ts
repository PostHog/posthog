import { emitIngestionWarning } from '../common/ingestion-warnings'
import { IngestionWarningsOutput } from '../common/outputs'
import { IngestionOutputs } from '../outputs/ingestion-outputs'
import { BatchPipeline, BatchPipelineResultWithContext, OkResultWithContext } from './batch-pipeline.interface'
import { TeamIdContext } from './builders/batch-pipeline-builders'

export class IngestionWarningHandlingBatchPipeline<
    TInput,
    TOutput,
    CInput extends TeamIdContext,
    COutput extends TeamIdContext = CInput,
    R extends string = never,
> implements BatchPipeline<TInput, TOutput, CInput, COutput, R>
{
    constructor(
        private outputs: IngestionOutputs<IngestionWarningsOutput>,
        private previousPipeline: BatchPipeline<TInput, TOutput, CInput, COutput, R>
    ) {}

    feed(elements: OkResultWithContext<TInput, CInput>[]): void {
        this.previousPipeline.feed(elements)
    }

    async next(): Promise<BatchPipelineResultWithContext<TOutput, COutput, R> | null> {
        const results = await this.previousPipeline.next()
        if (results === null) {
            return null
        }

        return results.map((resultWithContext) => {
            if (resultWithContext.context.warnings && resultWithContext.context.warnings.length > 0) {
                const warningPromises = resultWithContext.context.warnings.map((warning) =>
                    emitIngestionWarning(
                        this.outputs,
                        resultWithContext.context.team.id,
                        warning.type,
                        warning.details,
                        { key: warning.key, alwaysSend: warning.alwaysSend }
                    )
                )

                return {
                    result: resultWithContext.result,
                    context: {
                        ...resultWithContext.context,
                        sideEffects: [...resultWithContext.context.sideEffects, ...warningPromises],
                        warnings: [],
                    },
                }
            }
            return resultWithContext
        })
    }
}
