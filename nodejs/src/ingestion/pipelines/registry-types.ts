import { BatchPipeline } from './batch-pipeline.interface'
import { BatchPipelineBuilder } from './builders/batch-pipeline-builders'

/**
 * Generic factory function type for creating pipelines.
 * Takes a builder and config, returns a buildable pipeline.
 */
export type PipelineFactory<TInput, TContext, TConfig> = (
    builder: BatchPipelineBuilder<TInput, TInput, TContext, TContext>,
    config: TConfig
) => { build(): BatchPipeline<TInput, void, TContext, TContext> }

/**
 * Map of implementation name to factory function.
 * The 'default' key is required and used when no implementation is specified.
 */
export type ImplementationsMap<TInput, TContext, TConfig> = {
    default: PipelineFactory<TInput, TContext, TConfig>
    [key: string]: PipelineFactory<TInput, TContext, TConfig>
}

/**
 * Configuration for a single lane within a pipeline.
 */
export type LaneConfig<TInput, TContext, TConfig> = {
    implementations: ImplementationsMap<TInput, TContext, TConfig>
}

/**
 * Map of lane name to lane configuration.
 * The 'default' key is required and used when no lane is specified.
 */
export type LanesMap<TInput, TContext, TConfig> = {
    default: LaneConfig<TInput, TContext, TConfig>
    [key: string]: LaneConfig<TInput, TContext, TConfig>
}

/**
 * Pipeline registry structure.
 * Contains all lanes and their implementations for a pipeline.
 */
export type PipelineRegistry<TInput, TContext, TConfig> = {
    lanes: LanesMap<TInput, TContext, TConfig>
}
