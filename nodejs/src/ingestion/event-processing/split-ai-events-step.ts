import { ok } from '../pipelines/results'
import { ProcessingStep } from '../pipelines/steps'
import { EventToEmit, ProcessedEvent } from './emit-event-step'
import { AI_EVENTS_OUTPUT } from './ingestion-outputs'

const LARGE_AI_PROPERTIES = new Set([
    '$ai_input',
    '$ai_output',
    '$ai_output_choices',
    '$ai_input_state',
    '$ai_output_state',
    '$ai_tools',
])

export interface SplitAiEventsStepInput<O extends string = string> {
    eventsToEmit: EventToEmit<O>[]
}

function maybeStripAiProperties<O extends string>(entry: EventToEmit<O>): EventToEmit<O | typeof AI_EVENTS_OUTPUT>[] {
    if (entry.output === AI_EVENTS_OUTPUT) {
        return [entry]
    }

    const properties = entry.event.properties ?? {}

    let hasLarge = false
    for (const key of LARGE_AI_PROPERTIES) {
        if (key in properties) {
            hasLarge = true
            break
        }
    }

    if (!hasLarge) {
        return [entry]
    }

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

export function createSplitAiEventsStep<O extends string, T extends SplitAiEventsStepInput<O>>(): ProcessingStep<T, T> {
    return function splitAiEventsStep(input) {
        return Promise.resolve(
            ok({
                ...input,
                eventsToEmit: input.eventsToEmit.flatMap((entry) => maybeStripAiProperties(entry)),
            })
        )
    }
}
