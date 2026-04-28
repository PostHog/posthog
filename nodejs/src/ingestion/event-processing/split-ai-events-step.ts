import { ProcessedEvent } from '../../types'
import { AI_EVENT_TYPES } from '../ai'
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
    /**
     * '*' for all teams, or a small array of enabled team IDs.
     * Hot-path lookup uses Array.includes; expected size is ~3–10, which beats Set in V8.
     */
    enabledTeams: number[] | '*'
    /**
     * Teams whose events copy should have heavy AI properties stripped — i.e. the post-migration final state
     * where heavy columns live only in the AI events table. '*' for all teams, or a small array of team IDs.
     * Teams not listed here keep double-writing the full event to both outputs.
     */
    stripHeavyTeams: number[] | '*'
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
    stripHeavyForTeam: boolean
): EventToEmit<EventOutput | AiEventOutput>[] {
    const properties = entry.event.properties ?? {}
    const isAiEvent = AI_EVENT_TYPES.has(entry.event.event)

    if (!isAiEvent) {
        return [entry]
    }

    if (!stripHeavyForTeam || !hasLargeAiProperties(properties)) {
        // Duplicate unchanged to both outputs
        return [entry, { event: entry.event, output: AI_EVENTS_OUTPUT }]
    }

    // Strip heavy props from events copy (only when team is in stripHeavyTeams)
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

function parseTeamsList(teamsStr: string): number[] | '*' {
    if (teamsStr === '*') {
        return '*'
    }
    return teamsStr
        .split(',')
        .map((s) => parseInt(s.trim(), 10))
        .filter((n) => !isNaN(n))
}

export function parseSplitAiEventsConfig(
    enabled: boolean,
    teamsStr: string,
    stripHeavyTeamsStr: string
): SplitAiEventsStepConfig {
    return {
        enabled,
        enabledTeams: parseTeamsList(teamsStr),
        stripHeavyTeams: parseTeamsList(stripHeavyTeamsStr),
    }
}

export function createSplitAiEventsStep<T extends SplitAiEventsStepInput>(
    config: SplitAiEventsStepConfig
): ProcessingStep<T, T & SplitAiEventsStepOutput> {
    return function splitAiEventsStep(input) {
        if (!config.enabled || (config.enabledTeams !== '*' && !config.enabledTeams.includes(input.teamId))) {
            return Promise.resolve(ok(input))
        }

        const stripHeavyForTeam = config.stripHeavyTeams === '*' || config.stripHeavyTeams.includes(input.teamId)

        return Promise.resolve(
            ok({
                ...input,
                eventsToEmit: input.eventsToEmit.flatMap((entry) => maybeStripAiProperties(entry, stripHeavyForTeam)),
            })
        )
    }
}
