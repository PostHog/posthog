import { ProcessedEvent } from '../../types'
import { AI_EVENTS_OUTPUT, AiEventOutput, EventOutput } from '../analytics/outputs'
import { ok } from '../pipelines/results'
import { ProcessingStep } from '../pipelines/steps'
import { EventToEmit } from './emit-event-step'

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

function maybeStripAiProperties(entry: EventToEmit<EventOutput>): EventToEmit<EventOutput | AiEventOutput>[] {
    const properties = entry.event.properties ?? {}

    if (!hasLargeAiProperties(properties)) {
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

export function parseSplitAiEventsConfig(enabled: boolean, teamsStr: string): SplitAiEventsStepConfig {
    if (teamsStr === '*') {
        return { enabled, enabledTeams: '*' }
    }
    const enabledTeams = new Set(
        teamsStr
            .split(',')
            .map((s) => parseInt(s.trim(), 10))
            .filter((n) => !isNaN(n))
    )
    return { enabled, enabledTeams }
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
                eventsToEmit: input.eventsToEmit.flatMap((entry) => maybeStripAiProperties(entry)),
            })
        )
    }
}
