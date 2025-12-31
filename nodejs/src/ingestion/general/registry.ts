import { PipelineRegistry } from '../pipelines/registry-types'
import { MainPipelineConfig, MainPipelineContext, MainPipelineInput, createMainPipeline } from './main-pipeline'

// Pipeline-specific type aliases
export type Input = MainPipelineInput
export type Context = MainPipelineContext
export type Config = MainPipelineConfig

/**
 * Registry for the general ingestion pipeline.
 *
 * Lanes:
 * - default: Standard event processing
 * - overflow: High-volume event processing (rate-limited events)
 * - historical: Historical data backfills
 * - async: Asynchronous/deferred processing
 *
 * All lanes currently use the same 'default' implementation (createMainPipeline).
 * New implementations can be added per lane as needed.
 */
export const pipeline: PipelineRegistry<Input, Context, Config> = {
    lanes: {
        default: {
            implementations: {
                default: createMainPipeline,
            },
        },
        overflow: {
            implementations: {
                default: createMainPipeline,
            },
        },
        historical: {
            implementations: {
                default: createMainPipeline,
            },
        },
        async: {
            implementations: {
                default: createMainPipeline,
            },
        },
    },
}
