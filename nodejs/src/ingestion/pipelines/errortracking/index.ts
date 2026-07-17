// Error tracking ingestion pipeline exports
// This module processes $exception events from the error tracking ingestion topic

export {
    ErrorTrackingConsumer,
    type ErrorTrackingConsumerOptions,
    type ErrorTrackingConsumerDeps,
    type ErrorTrackingHogTransformer,
} from './error-tracking-consumer'
export { CymbalClient, type CymbalClientConfig } from './cymbal'
export { createErrorTrackingPipeline, runErrorTrackingPipeline } from './error-tracking-pipeline'
export type {
    ErrorTrackingPipelineConfig,
    ErrorTrackingPipelineInput,
    ErrorTrackingPipelineOutput,
} from './error-tracking-pipeline'

// Steps
export { createCymbalProcessingStep } from './cymbal-processing-step'
