import { DEFAULT_PRODUCER } from '../kafka/producer-definitions'

export const EVENTS_OUTPUT = 'events' as const
export type EventOutput = typeof EVENTS_OUTPUT

export const AI_EVENTS_OUTPUT = 'ai_events' as const
export type AiEventOutput = typeof AI_EVENTS_OUTPUT

export const HEATMAPS_OUTPUT = 'heatmaps' as const
export type HeatmapsOutput = typeof HEATMAPS_OUTPUT

/** Default output-to-producer mapping. Can be overridden via INGESTION_OUTPUT_{NAME}_PRODUCER env vars. */
export const DEFAULT_OUTPUT_PRODUCER_MAP = {
    [EVENTS_OUTPUT]: DEFAULT_PRODUCER,
    [AI_EVENTS_OUTPUT]: DEFAULT_PRODUCER,
    [HEATMAPS_OUTPUT]: DEFAULT_PRODUCER,
} as const
