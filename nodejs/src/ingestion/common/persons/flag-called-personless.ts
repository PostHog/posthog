import { parseTeamsList } from '~/common/utils/env-utils'
import { logger } from '~/common/utils/logger'
import { buildTeamGate } from '~/ingestion/common/team-gate'
import {
    DEFAULT_FLAG_CALLED_PERSONLESS_DEFAULT_TEAMS,
    DEFAULT_FLAG_CALLED_PERSONLESS_EXCLUDED_TEAMS,
} from '~/ingestion/config'
import { PluginEvent } from '~/plugin-scaffold'
import { ValueMatcher } from '~/types'

export const FEATURE_FLAG_CALLED_EVENT = '$feature_flag_called'

/**
 * Builds the team matcher for the $feature_flag_called personless default (see #60581).
 *
 * The exclusion list holds a team back from an allowlist of '*', which is what lets the
 * default go fleet-wide at all. A team whose running experiment breaks down by a person
 * property that its flag-called events carry loses that breakdown once those events go
 * personless, so it is named here instead of enumerating every other team.
 */
export function buildFlagCalledPersonlessMatcher(
    flagCalledPersonlessDefaultTeams: string = DEFAULT_FLAG_CALLED_PERSONLESS_DEFAULT_TEAMS,
    flagCalledPersonlessExcludedTeams: string = DEFAULT_FLAG_CALLED_PERSONLESS_EXCLUDED_TEAMS
): ValueMatcher<number> {
    const excludedTeams = parseTeamsList(flagCalledPersonlessExcludedTeams)
    if (excludedTeams === '*') {
        // An operator's '*' exclusion means "off": the escape hatch fails toward leaving
        // person processing alone.
        logger.warn('FLAG_CALLED_PERSONLESS_EXCLUDED_TEAMS is "*", disabling the personless default')
        return () => false
    }
    return buildTeamGate(parseTeamsList(flagCalledPersonlessDefaultTeams), excludedTeams)
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
 * evaluation does not create orphan person profiles (see #60581).
 *
 * `processPersonExplicitlyTrue` must be supplied by the caller. normalizeProcessPerson
 * rewrites $process_person_profile before this runs, so the event no longer shows whether
 * the client set it to true.
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
