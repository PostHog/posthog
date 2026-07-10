import { IngestionWarningsOutput } from '~/common/outputs'
import { IngestionOutputs } from '~/common/outputs/ingestion-outputs'
import { emitIngestionWarning } from '~/ingestion/common/ingestion-warnings'

import { TeamIdContext } from './builders/chunk-pipeline-builders'
import { ChunkPipeline, ChunkPipelineResultWithContext, OkResultWithContext } from './chunk-pipeline.interface'

export class IngestionWarningHandlingChunkPipeline<
    TInput,
    TOutput,
    CInput extends TeamIdContext,
    COutput extends TeamIdContext = CInput,
    R extends string = never,
> implements ChunkPipeline<TInput, TOutput, CInput, COutput, R>
{
    constructor(
        private outputs: IngestionOutputs<IngestionWarningsOutput>,
        private previousPipeline: ChunkPipeline<TInput, TOutput, CInput, COutput, R>
    ) {}

    feed(elements: OkResultWithContext<TInput, CInput>[]): void {
        this.previousPipeline.feed(elements)
    }

    async next(): Promise<ChunkPipelineResultWithContext<TOutput, COutput, R> | null> {
        const results = await this.previousPipeline.next()
        if (results === null) {
            return null
        }

        return results.map((resultWithContext) => {
            if (resultWithContext.context.warnings && resultWithContext.context.warnings.length > 0) {
                const warningPromises = resultWithContext.context.warnings.map((warning) =>
                    emitIngestionWarning(this.outputs, resultWithContext.context.team.id, warning)
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
