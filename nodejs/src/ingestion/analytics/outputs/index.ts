export { EVENTS_OUTPUT, type EventOutput } from '~/common/outputs'
export {
    PERSONS_OUTPUT,
    type PersonsOutput,
    PERSON_DISTINCT_IDS_OUTPUT,
    type PersonDistinctIdsOutput,
} from '~/common/outputs/persons'

export const AI_EVENTS_OUTPUT = 'ai_events' as const
export type AiEventOutput = typeof AI_EVENTS_OUTPUT

export const ASYNC_OUTPUT = 'async' as const
export type AsyncOutput = typeof ASYNC_OUTPUT
