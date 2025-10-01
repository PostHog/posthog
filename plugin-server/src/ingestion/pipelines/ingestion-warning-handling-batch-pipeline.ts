import { KafkaProducerWrapper } from '../../kafka/producer'
import { Team } from '../../types'
import { captureIngestionWarning } from '../../worker/ingestion/utils'
import { BatchPipeline, BatchPipelineResultWithContext } from './batch-pipeline.interface'

export class IngestionWarningHandlingBatchPipeline<TInput, TOutput, CInput extends { team: Team }>
    implements BatchPipeline<TInput, TOutput, CInput>
{
    constructor(
        private kafkaProducer: KafkaProducerWrapper,
        private subPipeline: BatchPipeline<TInput, TOutput, CInput>
    ) {}

    feed(elements: BatchPipelineResultWithContext<TInput, CInput>): void {
        this.subPipeline.feed(elements)
    }

    async next(): Promise<BatchPipelineResultWithContext<TOutput, CInput> | null> {
        const results = await this.subPipeline.next()
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
                        warning.details
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
