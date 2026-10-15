// Error tracking ingestion pipeline exports
// This module processes $exception events from the error tracking ingestion topic

export { createErrorTrackingConsumer, type ErrorTrackingLaneConfig, type ErrorTrackingSharedScope } from './consumer'
export { CymbalClient, type CymbalClientConfig } from './cymbal'
export { createErrorTrackingPipeline } from './error-tracking-pipeline'
export type {
    ErrorTrackingHogTransformer,
    ErrorTrackingPipelineConfig,
    ErrorTrackingPipelineInput,
    ErrorTrackingPipelineOutput,
} from './error-tracking-pipeline'

// Steps
export { createCymbalProcessingStep } from './cymbal-processing-step'
