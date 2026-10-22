import { FEATURE_FLAG_CALLED_EVENT } from 'scenes/feature-flags/flagEvaluationsTable'

import { FlagEvaluationsModeEnumApi } from '~/generated/core/api.schemas'
import { EventsQuery, NodeKind } from '~/queries/schema/schema-general'
import { setLatestVersionsOnQuery } from '~/queries/utils'
import { PropertyGroupFilter, TeamPublicType, TeamType, TrendResult } from '~/types'

import { MatchingFiltersInput, matchingFiltersToPropertyGroup } from './matchingFilters'

export const FLAG_CALLS_NOT_LOADABLE =
    "Feature flag calls are stored separately from other events, so they can't be loaded as a test event."

/**
 * Whether ingestion writes the team's flag calls to flag_evaluations instead of `events`. Destinations and
 * workflows still receive those calls, so a count on `events` alone misses them.
 */
export function storesFlagCallsOutsideEvents(team: TeamPublicType | TeamType | null): boolean {
    return team?.flag_evaluations_mode === FlagEvaluationsModeEnumApi.Number2
}

/**
 * The matchers that can match a flag call, as a property group to count on flag_evaluations, or null when none
 * can. A matcher on the flag call event or on all events can. So can a configuration with no event or action
 * matcher, because it matches every event. Action matchers are left out, so a flag call that only an action
 * matches is not counted.
 */
export function flagCallsMatchingFilters({
    events,
    actions,
    properties,
}: MatchingFiltersInput): PropertyGroupFilter | null {
    if (!events?.length && !actions?.length) {
        return matchingFiltersToPropertyGroup({ properties })
    }
    const flagCallMatchers = (events ?? []).filter(({ id }) => !id || id === FEATURE_FLAG_CALLED_EVENT)
    return flagCallMatchers.length ? matchingFiltersToPropertyGroup({ events: flagCallMatchers, properties }) : null
}

/**
 * Daily counts of the flag calls that `filters` match over the last `days` days. The events query runner reads
 * flag_evaluations for a query that names only the flag call event. The window starts a day early, so the first
 * day of a trends window over the same days is whole in every timezone.
 */
export function flagCallsDailyCountQuery(
    filters: PropertyGroupFilter,
    filterTestAccounts: boolean | undefined,
    days: number
): EventsQuery {
    return setLatestVersionsOnQuery({
        kind: NodeKind.EventsQuery,
        event: FEATURE_FLAG_CALLED_EVENT,
        select: ['toDate(timestamp)', 'count()'],
        fixedProperties: [filters],
        filterTestAccounts,
        after: `-${days + 1}d`,
        orderBy: ['toDate(timestamp) ASC'],
    })
}

/** Adds daily flag call counts to a trends series by date. A day outside the series is left out. */
export function withFlagCallCounts(
    series: Pick<TrendResult, 'data' | 'days' | 'count'>,
    rows: [string, number][]
): Pick<TrendResult, 'data' | 'count'> {
    const flagCallsByDay = new Map(rows)
    const added = series.days.map((day) => flagCallsByDay.get(day) ?? 0)
    return {
        data: series.data.map((value, index) => value + added[index]),
        count: series.count + added.reduce((sum, value) => sum + value, 0),
    }
}
