import { ProcessedEvent } from '../../types'
import { AI_EVENT_TYPES } from '../ai'
import { ok } from '../pipelines/results'
import { ProcessingStep } from '../pipelines/steps'
import { EventToEmit } from './emit-event-step'
import { AI_EVENTS_OUTPUT, AiEventOutput, EventOutput } from './ingestion-outputs'

const LARGE_AI_PROPERTIES = new Set([
    '$ai_input',
    '$ai_output',
    '$ai_output_choices',
    '$ai_input_state',
    '$ai_output_state',
    '$ai_tools',
])

export interface SplitAiEventsStepConfig {
    enabled: boolean
    /** '*' for all teams, or a Set of enabled team IDs */
    enabledTeams: Set<number> | '*'
    /** When true, strip heavy AI properties from the events copy. When false, send unchanged to both outputs. */
    stripHeavyProperties: boolean
}

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

function maybeStripAiProperties(
    entry: EventToEmit<EventOutput>,
    stripHeavyProperties: boolean
): EventToEmit<EventOutput | AiEventOutput>[] {
    const properties = entry.event.properties ?? {}
    const isAiEvent = AI_EVENT_TYPES.has(entry.event.event)

    if (!isAiEvent) {
        return [entry]
    }

    if (!hasLargeAiProperties(properties) || !stripHeavyProperties) {
        // Duplicate unchanged to both outputs
        return [entry, { event: entry.event, output: AI_EVENTS_OUTPUT }]
    }

    // Strip heavy props from events copy (only when stripHeavyProperties is true)
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

export function parseSplitAiEventsConfig(
    enabled: boolean,
    teamsStr: string,
    stripHeavy: boolean
): SplitAiEventsStepConfig {
    if (teamsStr === '*') {
        return { enabled, enabledTeams: '*', stripHeavyProperties: stripHeavy }
    }
    const enabledTeams = new Set(
        teamsStr
            .split(',')
            .map((s) => parseInt(s.trim(), 10))
            .filter((n) => !isNaN(n))
    )
    return { enabled, enabledTeams, stripHeavyProperties: stripHeavy }
}

export function createSplitAiEventsStep<T extends SplitAiEventsStepInput>(
    config: SplitAiEventsStepConfig
): ProcessingStep<T, T & SplitAiEventsStepOutput> {
    return function splitAiEventsStep(input) {
        if (!config.enabled || (config.enabledTeams !== '*' && !config.enabledTeams.has(input.teamId))) {
            return Promise.resolve(ok(input))
        }

        return Promise.resolve(
            ok({
                ...input,
                eventsToEmit: input.eventsToEmit.flatMap((entry) =>
                    maybeStripAiProperties(entry, config.stripHeavyProperties)
                ),
            })
        )
    }
}
