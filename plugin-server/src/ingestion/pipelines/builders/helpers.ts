import { BufferingBatchPipeline } from '../buffering-batch-pipeline'
import { BatchPipelineBuilder } from './batch-pipeline-builders'
import { StartPipelineBuilder } from './pipeline-builders'

export function newBatchPipelineBuilder<T, C>(): BatchPipelineBuilder<T, T, C> {
    return new BatchPipelineBuilder(new BufferingBatchPipeline<T, C>())
}

export function newPipelineBuilder<T, C>(): StartPipelineBuilder<T, C> {
    return new StartPipelineBuilder<T, C>()
}
