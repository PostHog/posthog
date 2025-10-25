import { KafkaProducerWrapper } from '../../kafka/producer'
import { Team } from '../../types'
import { captureIngestionWarning } from '../../worker/ingestion/utils'
import { BatchPipeline, BatchPipelineResultWithContext } from './batch-pipeline.interface'

export class IngestionWarningHandlingBatchPipeline<
    TInput,
    TOutput,
    CInput extends { team: Team },
    COutput extends { team: Team } = CInput,
> implements BatchPipeline<TInput, TOutput, CInput, COutput>
{
    constructor(
        private kafkaProducer: KafkaProducerWrapper,
        private previousPipeline: BatchPipeline<TInput, TOutput, CInput, COutput>
    ) {}

    feed(elements: BatchPipelineResultWithContext<TInput, CInput>): void {
        this.previousPipeline.feed(elements)
    }

    async next(): Promise<BatchPipelineResultWithContext<TOutput, COutput> | null> {
        const results = await this.previousPipeline.next()
        if (results === null) {
            return null
        }

        return results.map((resultWithContext) => {
            if (resultWithContext.context.warnings && resultWithContext.context.warnings.length > 0) {
                const warningPromises = resultWithContext.context.warnings.map((warning) =>
                    captureIngestionWarning(
                        this.kafkaProducer,
                        resultWithContext.context.team.id,
                        warning.type,
                        warning.details,
                        { alwaysSend: warning.alwaysSend }
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
