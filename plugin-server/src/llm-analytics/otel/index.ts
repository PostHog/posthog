/**
 * OpenTelemetry traces ingestion for PostHog LLM Analytics.
 *
 * This module provides transformation of OpenTelemetry spans to PostHog AI events.
 * It supports both PostHog-native and GenAI semantic conventions.
 *
 * Architecture:
 * 1. Python API endpoint receives OTLP protobuf HTTP requests
 * 2. Python parses protobuf and creates PostHog events
 * 3. Events go through standard ingestion pipeline (Kafka)
 * 4. Plugin-server processes AI events (cost calculation, normalization)
 *
 * This TypeScript code can be used for:
 * - Documentation of the transformation logic
 * - Testing transformation behavior
 * - Future: Direct TypeScript-based ingestion if needed
 */

export { transformSpanToAIEvent, spanUsesKnownConventions, OTEL_TRANSFORMER_VERSION } from './transformer'
export { extractPostHogNativeAttributes, hasPostHogAttributes } from './conventions/posthog-native'
export { extractGenAIAttributes, hasGenAIAttributes } from './conventions/genai'
export { OTEL_LIMITS } from './validation'
export type * from './types'
