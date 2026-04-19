export { EVENTS_OUTPUT, EventOutput } from '../../common/outputs'

export const AI_EVENTS_OUTPUT = 'ai_events' as const
export type AiEventOutput = typeof AI_EVENTS_OUTPUT

export const HEATMAPS_OUTPUT = 'heatmaps' as const
export type HeatmapsOutput = typeof HEATMAPS_OUTPUT

export const ASYNC_OUTPUT = 'async' as const
export type AsyncOutput = typeof ASYNC_OUTPUT

export const PERSONS_OUTPUT = 'persons' as const
export type PersonsOutput = typeof PERSONS_OUTPUT

export const PERSON_DISTINCT_IDS_OUTPUT = 'person_distinct_ids' as const
export type PersonDistinctIdsOutput = typeof PERSON_DISTINCT_IDS_OUTPUT
