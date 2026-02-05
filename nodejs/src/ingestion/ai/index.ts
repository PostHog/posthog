/**
 * AI event processing module.
 *
 * This module provides the main entry point for AI event enrichment at ingestion time.
 */

export { createExpandOtelRawDataStep } from './otel-preprocessing'
export { AI_EVENT_TYPES, EventWithProperties, normalizeTraceProperties, processAiEvent } from './process-ai-event'
