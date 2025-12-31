import { PipelineRegistry } from '../pipelines/registry-types'
import {
    JoinedIngestionPipelineConfig,
    JoinedIngestionPipelineContext,
    JoinedIngestionPipelineInput,
    createJoinedIngestionPipeline,
} from './joined-ingestion-pipeline'

// Pipeline-specific type aliases
export type Input = JoinedIngestionPipelineInput
export type Context = JoinedIngestionPipelineContext
export type Config = JoinedIngestionPipelineConfig

/**
 * Registry for the general ingestion pipeline.
 *
 * Lanes:
 * - default: Standard event processing
 * - overflow: High-volume event processing (rate-limited events)
 * - historical: Historical data backfills
 * - async: Asynchronous/deferred processing
 *
 * All lanes currently use the same 'default' implementation (createJoinedIngestionPipeline).
 * New implementations can be added per lane as needed.
 */
export const pipeline: PipelineRegistry<Input, Context, Config> = {
    lanes: {
        default: {
            implementations: {
                default: createJoinedIngestionPipeline,
            },
        },
        overflow: {
            implementations: {
                default: createJoinedIngestionPipeline,
            },
        },
        historical: {
            implementations: {
                default: createJoinedIngestionPipeline,
            },
        },
        async: {
            implementations: {
                default: createJoinedIngestionPipeline,
            },
        },
    },
}
