import { RecordIngestionLagInput, createRecordIngestionLagStep } from '~/ingestion/common/steps/record-ingestion-lag'
import { PipelineBuilder } from '~/ingestion/framework/builders/pipeline-builders'
import { RetryOptions } from '~/ingestion/framework/retry'
import { ProcessingStep } from '~/ingestion/framework/steps'

/**
 * The tail every event pipeline ends with. The barrier makes the emit the point of no return:
 * a batch budget cannot cut an event that already produced, which would redeliver it and produce it again.
 */
export function createEmitSubpipeline<
    TInput,
    TCurrent,
    TEmitted extends RecordIngestionLagInput,
    C,
    R extends string,
    REmit extends string,
>(
    builder: PipelineBuilder<TInput, TCurrent, C, R>,
    emitStep: ProcessingStep<TCurrent, TEmitted, REmit>,
    options?: { retry?: RetryOptions }
): PipelineBuilder<TInput, TEmitted, C, R | REmit> {
    return builder.timeoutBarrier().pipe(emitStep, options).pipe(createRecordIngestionLagStep())
}
