import { FEATURE_FLAG_CALLED_EVENT, storesFlagCallsOutsideEvents } from 'scenes/feature-flags/flagEvaluationsTable'

import { performQuery } from '~/queries/query'
import { EventsQuery, NodeKind, TrendsQuery } from '~/queries/schema/schema-general'
import { setLatestVersionsOnQuery } from '~/queries/utils'
import { PropertyGroupFilter, TeamPublicType, TeamType, TrendResult } from '~/types'

import { MatchingFiltersInput, matchingFiltersToPropertyGroup } from './matchingFilters'

export const FLAG_CALLS_NOT_LOADABLE =
    "Feature flag calls are stored separately from other events, so they can't be loaded as a test event."

/**
 * The matchers that can match a flag call that `events` does not hold, as a property group to count on
 * flag_evaluations. Null when the team's flag calls are in `events`, or when no matcher can match one.
 * Destinations and workflows still receive those calls, so a count on `events` alone misses them.
 * A matcher on the flag call event or on all events can match one. So can a configuration with no event or
 * action matcher, because it matches every event. Action matchers are left out, so a flag call that only an
 * action matches is not counted.
 */
export function flagCallsOutsideEventsFilters(
    team: TeamPublicType | TeamType | null,
    { events, actions, properties }: MatchingFiltersInput
): PropertyGroupFilter | null {
    if (!storesFlagCallsOutsideEvents(team)) {
        return null
    }
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
function flagCallsDailyCountQuery(
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
    series: Pick<TrendResult, 'data' | 'days' | 'count'> | undefined,
    rows: [string, number][] | null
): Pick<TrendResult, 'data' | 'count'> {
    if (!series) {
        return { data: [], count: 0 }
    }
    const flagCallsByDay = new Map(rows)
    const added = series.days.map((day) => flagCallsByDay.get(day) ?? 0)
    return {
        data: series.data.map((value, index) => value + added[index]),
        count: series.count + added.reduce((sum, value) => sum + value, 0),
    }
}

/**
 * Runs a trends query over the last `days` days. When `flagCallFilters` is set, it also counts the flag calls
 * those filters match and adds them to the first series.
 */
export async function performTrendsQueryWithFlagCalls(
    trendsQuery: TrendsQuery,
    flagCallFilters: PropertyGroupFilter | null,
    days: number
): Promise<Pick<TrendResult, 'data' | 'count' | 'labels'>> {
    const [trends, flagCalls] = await Promise.all([
        performQuery(trendsQuery),
        flagCallFilters
            ? performQuery(flagCallsDailyCountQuery(flagCallFilters, trendsQuery.filterTestAccounts, days))
            : null,
    ])
    const series = trends.results?.[0] as TrendResult | undefined
    const rows = (flagCalls?.results as [string, number][] | undefined) ?? null
    return { ...withFlagCallCounts(series, rows), labels: series?.labels ?? [] }
}
