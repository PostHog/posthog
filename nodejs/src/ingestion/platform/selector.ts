import { Config, Context, Input, pipelines } from './registry'
import { PipelineFactory } from './types'

// Type alias for pipeline factory
export type Factory = PipelineFactory<Input, Context, Config>

/**
 * Selects a pipeline factory based on pipeline name, lane, and implementation.
 *
 * @param pipelineName - The pipeline to use (e.g., 'general', 'replay', 'logs')
 * @param lane - The lane within the pipeline (e.g., 'default', 'overflow'). Uses 'default' if not specified.
 * @param implementation - The implementation within the lane. Uses 'default' if not specified.
 * @returns The pipeline factory function
 * @throws Error if pipeline, lane, or implementation is not found (crashes the process)
 */
export function selectPipelineFactory(
    pipelineName: string,
    lane: string | undefined | null,
    implementation: string | undefined | null
): Factory {
    const registry = pipelines[pipelineName]
    if (!registry) {
        throw new Error(
            `Unknown pipeline: '${pipelineName}'. Available pipelines: ${Object.keys(pipelines).join(', ')}`
        )
    }

    // Use 'default' lane if not specified
    const effectiveLane = lane ?? 'default'

    const laneConfig = registry.lanes[effectiveLane]
    if (!laneConfig) {
        throw new Error(
            `Unknown lane '${effectiveLane}' for pipeline '${pipelineName}'. ` +
                `Available lanes: ${Object.keys(registry.lanes).join(', ')}`
        )
    }

    // Use 'default' implementation if not specified
    const effectiveImpl = implementation ?? 'default'

    const factory = laneConfig.implementations[effectiveImpl]
    if (!factory) {
        throw new Error(
            `Unknown implementation '${effectiveImpl}' for lane '${effectiveLane}' ` +
                `in pipeline '${pipelineName}'. ` +
                `Available implementations: ${Object.keys(laneConfig.implementations).join(', ')}`
        )
    }

    return factory
}
