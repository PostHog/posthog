export { EVENTS_OUTPUT, EventOutput } from '../common/outputs'

export const AI_EVENTS_OUTPUT = 'ai_events' as const
export type AiEventOutput = typeof AI_EVENTS_OUTPUT

export const HEATMAPS_OUTPUT = 'heatmaps' as const
export type HeatmapsOutput = typeof HEATMAPS_OUTPUT

export const ASYNC_OUTPUT = 'async' as const
export type AsyncOutput = typeof ASYNC_OUTPUT
