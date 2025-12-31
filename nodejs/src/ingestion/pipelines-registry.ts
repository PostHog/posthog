import { Config, Context, Input, pipeline as generalPipeline } from './general'
import { PipelineRegistry } from './pipelines/registry-types'

// Re-export pipeline types for use by consumers
export type { Config, Context, Input }

// Type alias for the pipeline registry
export type Registry = PipelineRegistry<Input, Context, Config>

/**
 * Global registry of all available pipelines.
 *
 * Each pipeline has lanes, and each lane has implementations.
 * The 'default' lane and 'default' implementation are required for each pipeline.
 *
 * To add a new pipeline:
 * 1. Create a registry file in the pipeline's folder (e.g., general/registry.ts)
 * 2. Define the PipelineRegistry with lanes and implementations
 * 3. Add it to this map
 */
export const pipelines: Record<string, Registry> = {
    general: generalPipeline,
}

export type PipelineName = keyof typeof pipelines
