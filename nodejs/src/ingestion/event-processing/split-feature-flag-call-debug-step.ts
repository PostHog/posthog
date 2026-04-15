import { ProcessedEvent } from '../../types'
import { EventOutput, FEATURE_FLAG_CALL_DEBUG_OUTPUT, FeatureFlagCallDebugOutput } from '../analytics/outputs'
import { ok } from '../pipelines/results'
import { ProcessingStep } from '../pipelines/steps'
import { EventToEmit } from './emit-event-step'

const FF_CALLED_KEEP_PROPERTIES = new Set(['$feature_flag', '$feature_flag_response', '$feature_flag_payload'])

export interface SplitFeatureFlagCallDebugConfig {
    enabled: boolean
    /** '*' for all teams, or a Set of enabled team IDs */
    enabledTeams: Set<number> | '*'
    /** When true, strip non-core properties from the events copy. When false, send unchanged to both outputs. */
    stripProperties: boolean
}

export interface SplitFeatureFlagCallDebugInput {
    eventsToEmit: EventToEmit<EventOutput>[]
    teamId: number
}

export type SplitFeatureFlagCallDebugOutput = Omit<SplitFeatureFlagCallDebugInput, 'eventsToEmit'> & {
    eventsToEmit: EventToEmit<EventOutput | FeatureFlagCallDebugOutput>[]
}

function stripToCoreProperties(properties: Record<string, unknown>): Record<string, unknown> {
    const stripped: Record<string, unknown> = {}
    for (const key of FF_CALLED_KEEP_PROPERTIES) {
        if (key in properties) {
            stripped[key] = properties[key]
        }
    }
    return stripped
}

function maybeSplitFeatureFlagEvent(
    entry: EventToEmit<EventOutput>,
    stripProperties: boolean
): EventToEmit<EventOutput | FeatureFlagCallDebugOutput>[] {
    if (entry.event.event !== '$feature_flag_called') {
        return [entry]
    }

    if (!stripProperties) {
        // Shadow mode: send unchanged to both outputs for validation
        return [entry, { event: entry.event, output: FEATURE_FLAG_CALL_DEBUG_OUTPUT }]
    }

    const properties = entry.event.properties ?? {}
    const strippedEvent: ProcessedEvent = { ...entry.event, properties: stripToCoreProperties(properties) }

    return [
        { event: strippedEvent, output: entry.output },
        { event: entry.event, output: FEATURE_FLAG_CALL_DEBUG_OUTPUT },
    ]
}

export function parseSplitFeatureFlagCallDebugConfig(
    enabled: boolean,
    teamsStr: string,
    stripProperties: boolean
): SplitFeatureFlagCallDebugConfig {
    if (teamsStr === '*') {
        return { enabled, enabledTeams: '*', stripProperties }
    }
    const enabledTeams = new Set(
        teamsStr
            .split(',')
            .map((s) => parseInt(s.trim(), 10))
            .filter((n) => !isNaN(n))
    )
    return { enabled, enabledTeams, stripProperties }
}

export function createSplitFeatureFlagCallDebugStep<T extends SplitFeatureFlagCallDebugInput>(
    config: SplitFeatureFlagCallDebugConfig
): ProcessingStep<T, T & SplitFeatureFlagCallDebugOutput> {
    return function splitFeatureFlagCallDebugStep(input) {
        if (!config.enabled || (config.enabledTeams !== '*' && !config.enabledTeams.has(input.teamId))) {
            return Promise.resolve(ok(input))
        }

        return Promise.resolve(
            ok({
                ...input,
                eventsToEmit: input.eventsToEmit.flatMap((entry) =>
                    maybeSplitFeatureFlagEvent(entry, config.stripProperties)
                ),
            })
        )
    }
}
