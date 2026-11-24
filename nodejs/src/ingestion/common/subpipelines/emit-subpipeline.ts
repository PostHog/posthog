import { RecordIngestionLagInput, createRecordIngestionLagStep } from '~/ingestion/common/steps/record-ingestion-lag'
import { PipelineBuilder } from '~/ingestion/framework/builders/pipeline-builders'
import { RetryOptions } from '~/ingestion/framework/retry'
import { ProcessingStep } from '~/ingestion/framework/steps'

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
    // A batch budget must not cut an event after it produced: the redelivery would produce it again.
    return builder.timeoutBarrier().pipe(emitStep, options).pipe(createRecordIngestionLagStep())
}
