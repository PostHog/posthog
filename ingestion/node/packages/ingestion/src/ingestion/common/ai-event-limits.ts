/**
 * Mirror of products/ai_observability/shared/crosslang/ai_event_limits.json, in decimal bytes. Edit that file first,
 * then these constants. The parity test in ai-event-limits.test.ts fails when they differ.
 */
export const AI_MAX_EVENT_BYTES_CEILING = 48_000_000
export const AI_INCLUDED_BYTES_PER_EVENT = 100_000
export const AI_MEDIA_OFFLOAD_MIN_BYTES = 15_000
