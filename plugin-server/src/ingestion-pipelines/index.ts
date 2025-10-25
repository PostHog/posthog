/**
 * Ingestion Pipelines Module
 *
 * This module contains the future architecture for ingestion pipelines.
 * Each pipeline is defined in its own file, making the system more modular and easier to understand.
 *
 * Pipeline Structure:
 * 1. Preprocessing Subpipeline - Common preprocessing for all events (validation, enrichment)
 * 2. Event Routing - Routes events to specialized pipelines based on event type
 * 3. Specialized Pipelines:
 *    - Analytics Pipeline: Regular events that get stored in ClickHouse events table
 *    - Heatmap Pipeline: Heatmap events that get sent to the heatmaps topic
 *    - Client Ingestion Warning Pipeline: Warning events that get logged but not stored
 *
 * Benefits of this architecture:
 * - Clear separation of concerns
 * - Each pipeline can be tested independently
 * - Easy to add new pipeline types
 * - Reusable preprocessing logic
 * - Self-documenting code structure
 */

export { applyPreprocessingSubpipeline, type PreprocessingSubpipelineConfig } from './preprocessing-subpipeline'

export { createAnalyticsPipeline, type AnalyticsPipelineConfig } from './analytics-pipeline'

export { createHeatmapPipeline, type HeatmapPipelineConfig } from './heatmap-pipeline'

export {
    createClientIngestionWarningPipeline,
    type ClientIngestionWarningPipelineConfig,
} from './client-ingestion-warning-pipeline'

export {
    routeEventToPipeline,
    isClientIngestionWarningEvent,
    isHeatmapEvent,
    isAnalyticsEvent,
    type EventProcessingPipelineInput,
} from './common'
