import { buildIntegerMatcher } from '~/common/config/config'
import { DEFAULT_FLAG_CALLED_PERSONLESS_DEFAULT_TEAMS } from '~/ingestion/config'
import { PluginEvent } from '~/plugin-scaffold'

export const FEATURE_FLAG_CALLED_EVENT = '$feature_flag_called'

/**
 * Builds the team matcher for the $feature_flag_called personless default. The per-event step
 * and the batch step both gate on team eligibility and must agree, so they share this one
 * construction site — a divergent trim/star/default here would desync the two phases (the
 * batch step would insert rows the per-event step never claims, or vice versa).
 */
export function buildFlagCalledPersonlessMatcher(
    flagCalledPersonlessDefaultTeams: string = DEFAULT_FLAG_CALLED_PERSONLESS_DEFAULT_TEAMS
): (teamId: number) => boolean {
    return buildIntegerMatcher(flagCalledPersonlessDefaultTeams.trim(), true)
}

/**
 * Group-keyed experiment exposure queries read the $group_N columns from the exposure
 * event, and createEvent strips those for personless events. Events carrying group keys
 * must stay personful or their exposures disappear from group-aggregated experiments.
 * Checking $groups alone is sufficient: SDKs only ever send group keys as $groups, and
 * $group_N is an internal representation the groups step derives from $groups (and only
 * when processPerson stays true), so it never arrives here pre-expanded from a client.
 */
export function eventHasGroups(properties: PluginEvent['properties']): boolean {
    const groups = properties?.$groups
    return typeof groups === 'object' && groups !== null && !Array.isArray(groups) && Object.keys(groups).length > 0
}

/**
 * Whether a $feature_flag_called event should default to personless so server-side flag
 * evaluation does not create orphan person profiles (see #60581). Shared by the per-event
 * step that makes the final decision and the batch step that pre-inserts the
 * posthog_personlessdistinctid rows.
 *
 * `processPersonExplicitlyTrue` must be supplied by the caller because the per-event step
 * runs after normalizeProcessPerson has stripped $process_person_profile, while the batch
 * step reads it from the raw event — each reads the signal from the source valid in its
 * pipeline phase.
 */
export function isFlagCalledPersonlessCandidate(
    event: Pick<PluginEvent, 'event' | 'properties'>,
    teamId: number,
    processPersonExplicitlyTrue: boolean,
    flagCalledDefaultEnabledForTeam: (teamId: number) => boolean
): boolean {
    return (
        event.event === FEATURE_FLAG_CALLED_EVENT &&
        !processPersonExplicitlyTrue &&
        !eventHasGroups(event.properties) &&
        flagCalledDefaultEnabledForTeam(teamId)
    )
}
