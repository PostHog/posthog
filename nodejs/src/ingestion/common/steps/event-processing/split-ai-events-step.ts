import { AI_EVENTS_OUTPUT, AiEventOutput, EventOutput } from '~/common/outputs'
import { AI_EVENT_TYPES } from '~/ingestion/common/ai-event-types'
import { ok } from '~/ingestion/framework/results'
import { ProcessingStep } from '~/ingestion/framework/steps'
import { ProcessedEvent } from '~/types'

import { EventToEmit } from './emit-event-step'

const LARGE_AI_PROPERTIES = new Set([
    '$ai_input',
    '$ai_output',
    '$ai_output_choices',
    '$ai_input_state',
    '$ai_output_state',
    '$ai_tools',
])

export interface SplitAiEventsStepInput {
    eventsToEmit: EventToEmit<EventOutput>[]
    teamId: number
}

export type SplitAiEventsStepOutput = Omit<SplitAiEventsStepInput, 'eventsToEmit'> & {
    eventsToEmit: EventToEmit<EventOutput | AiEventOutput>[]
}

function hasLargeAiProperties(properties: Record<string, unknown>): boolean {
    for (const key of LARGE_AI_PROPERTIES) {
        if (key in properties) {
            return true
        }
    }
    return false
}

function splitAiEvent(entry: EventToEmit<EventOutput>): EventToEmit<EventOutput | AiEventOutput>[] {
    const properties = entry.event.properties ?? {}

    if (!AI_EVENT_TYPES.has(entry.event.event)) {
        return [entry]
    }

    if (!hasLargeAiProperties(properties)) {
        // Nothing heavy to strip — duplicate unchanged to both outputs.
        return [entry, { event: entry.event, output: AI_EVENTS_OUTPUT }]
    }

    // The heavy AI properties live only on the dedicated ai_events table, so strip them
    // from the events copy and send the full event to AI_EVENTS_OUTPUT.
    const stripped: Record<string, unknown> = {}
    for (const [key, value] of Object.entries(properties)) {
        if (!LARGE_AI_PROPERTIES.has(key)) {
            stripped[key] = value
        }
    }

    const strippedEvent: ProcessedEvent = { ...entry.event, properties: stripped }

    return [
        { event: strippedEvent, output: entry.output },
        { event: entry.event, output: AI_EVENTS_OUTPUT },
    ]
}

export function createSplitAiEventsStep<T extends SplitAiEventsStepInput>(): ProcessingStep<
    T,
    T & SplitAiEventsStepOutput
> {
    return function splitAiEventsStep(input) {
        return Promise.resolve(
            ok({
                ...input,
                eventsToEmit: input.eventsToEmit.flatMap((entry) => splitAiEvent(entry)),
            })
        )
    }
}
