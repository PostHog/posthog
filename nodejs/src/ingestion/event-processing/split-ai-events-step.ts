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
     * '*' for all teams, or a small array of always-routed team IDs.
     * Hot-path lookup uses Array.includes; expected size is ~3–10, which beats Set in V8.
     */
    enabledTeams: number[] | '*'
    /**
     * Sticky percentage rollout (0-100), unioned with enabledTeams. A team is routed if it's
     * in the allowlist OR its bucket falls under the percentage. Bucketing is deterministic on
     * team_id, so the rollout is monotonic — every team in at X% stays in at any Y% > X%.
     */
    enabledPercentage: number
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

function clampPercentage(pct: number): number {
    if (Number.isNaN(pct) || pct <= 0) {
        return 0
    }
    if (pct >= 100) {
        return 100
    }
    return pct
}

/**
 * Stable bucket [0, 99] for a team id. Knuth's multiplicative hash so consecutive
 * team ids don't cluster into the same bucket.
 */
function teamRolloutBucket(teamId: number): number {
    return (Math.imul(teamId, 2654435761) >>> 0) % 100
}

function isTeamRouted(teams: number[] | '*', percentage: number, teamId: number): boolean {
    if (teams === '*' || percentage >= 100) {
        return true
    }
    if (teams.includes(teamId)) {
        return true
    }
    if (percentage <= 0) {
        return false
    }
    return teamRolloutBucket(teamId) < percentage
}

export function parseSplitAiEventsConfig(
    enabled: boolean,
    teamsStr: string,
    stripHeavyTeamsStr: string,
    percentage: number = 0
): SplitAiEventsStepConfig {
    return {
        enabled,
        enabledTeams: parseTeamsList(teamsStr),
        enabledPercentage: clampPercentage(percentage),
        stripHeavyTeams: parseTeamsList(stripHeavyTeamsStr),
    }
}

export function createSplitAiEventsStep<T extends SplitAiEventsStepInput>(
    config: SplitAiEventsStepConfig
): ProcessingStep<T, T & SplitAiEventsStepOutput> {
    return function splitAiEventsStep(input) {
        if (!config.enabled || !isTeamRouted(config.enabledTeams, config.enabledPercentage, input.teamId)) {
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
