import { convertPropertiesToPropertyGroup, isEventPropertyFilter } from 'lib/components/PropertyFilters/utils'
import { FEATURE_FLAG_CALLED_EVENT, storesFlagCallsOutsideEvents } from 'scenes/feature-flags/flagEvaluationsTable'

import { performQuery } from '~/queries/query'
import { EventsQuery, NodeKind, TrendsQuery } from '~/queries/schema/schema-general'
import { hogql, setLatestVersionsOnQuery } from '~/queries/utils'
import {
    CyclotronJobFilterPropertyFilter,
    CyclotronJobInvocationGlobals,
    EventPropertyFilter,
    FilterLogicalOperator,
    HogQLPropertyFilter,
    PropertyFilterType,
    PropertyGroupFilter,
    PropertyOperator,
    TeamPublicType,
    TeamType,
    TrendResult,
} from '~/types'

import { MatchingFiltersInput, matchingFiltersToPropertyGroup } from './matchingFilters'

export const FLAG_CALLS_NOT_LOADABLE =
    "Feature flag calls are stored separately from other events, so they can't be loaded as a test event."

const NOT_A_FLAG_CALL: HogQLPropertyFilter = {
    type: PropertyFilterType.HogQL,
    key: hogql`event != ${FEATURE_FLAG_CALLED_EVENT}`,
}

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
 * Whether the team's flag calls are outside `events` and every matcher names the flag call event. A search of
 * `events` then finds no recent event that the matchers match.
 */
export function matchesOnlyFlagCallsOutsideEvents(
    team: TeamPublicType | TeamType | null,
    { events, actions }: MatchingFiltersInput
): boolean {
    return (
        storesFlagCallsOutsideEvents(team) &&
        !actions?.length &&
        !!events?.length &&
        events.every(({ id }) => id === FEATURE_FLAG_CALLED_EVENT)
    )
}

/**
 * Daily counts of the flag calls that `filters` match over the last `days` days. The events query runner reads
 * flag_evaluations for a query that names only the flag call event. The window starts a day early, so the first
 * day of a trends window over the same days is whole in every timezone. The count takes the modifiers of
 * `trendsQuery`, so a person filter reads the same person properties in both counts.
 */
function flagCallsDailyCountQuery(
    filters: PropertyGroupFilter,
    { filterTestAccounts, modifiers }: Pick<TrendsQuery, 'filterTestAccounts' | 'modifiers'>,
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
        modifiers,
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
    // With no flag call rows, the series can be a Storybook mock that has no `days`.
    if (!rows) {
        return { data: series.data, count: series.count }
    }
    const flagCallsByDay = new Map(rows)
    const added = series.days.map((day) => flagCallsByDay.get(day) ?? 0)
    return {
        data: series.data.map((value, index) => value + added[index]),
        count: series.count + added.reduce((sum, value) => sum + value, 0),
    }
}

function exampleFlagKey({ events, properties }: MatchingFiltersInput): string {
    const filters: CyclotronJobFilterPropertyFilter[] = [
        ...(properties ?? []),
        ...(events ?? []).flatMap((event) => event.properties ?? []),
    ]
    const flagKeyFilter = filters.find(
        (filter): filter is EventPropertyFilter =>
            isEventPropertyFilter(filter) &&
            filter.key === '$feature_flag' &&
            filter.operator === PropertyOperator.Exact
    )
    const value = Array.isArray(flagKeyFilter?.value) ? flagKeyFilter.value[0] : flagKeyFilter?.value
    return value == null ? 'example-flag' : String(value)
}

/**
 * A copy of `globals` as a flag call that passes the matchers in a test run. It names the flag that an exact
 * `$feature_flag` filter in the matchers names. A global filter wins over a matcher's own filter.
 */
export function exampleFlagCall(
    globals: CyclotronJobInvocationGlobals,
    matchers: MatchingFiltersInput
): CyclotronJobInvocationGlobals {
    return {
        ...globals,
        event: {
            ...globals.event,
            event: FEATURE_FLAG_CALLED_EVENT,
            properties: { ...globals.event.properties, $feature_flag: exampleFlagKey(matchers) },
        },
    }
}

function withoutFlagCalls(properties: TrendsQuery['properties']): TrendsQuery['properties'] {
    return {
        type: FilterLogicalOperator.And,
        values: [
            convertPropertiesToPropertyGroup(properties),
            { type: FilterLogicalOperator.And, values: [NOT_A_FLAG_CALL] },
        ],
    }
}

/**
 * Runs `trendsQuery`. When `flagCallFilters` is set, the trends query leaves out flag calls. This function then
 * counts the flag calls that those filters match over the last `days` days on flag_evaluations, and adds them to the
 * first series. On mode 2, ingestion writes each flag call to flag_evaluations. It sends the same call to destinations
 * and workflows, so flag_evaluations holds exactly the flag calls they receive. A flag call from before the switch to
 * mode 2 is in both tables, because mode 1 wrote both, so the count includes it once. A flag call with no flag key
 * stays in `events` only, and the count leaves it out. `days` must cover the range of `trendsQuery`.
 */
export async function performTrendsQueryWithFlagCalls(
    trendsQuery: TrendsQuery,
    flagCallFilters: PropertyGroupFilter | null,
    days: number
): Promise<Pick<TrendResult, 'data' | 'count' | 'labels'>> {
    const [trends, flagCalls] = await Promise.all([
        performQuery(
            flagCallFilters ? { ...trendsQuery, properties: withoutFlagCalls(trendsQuery.properties) } : trendsQuery
        ),
        flagCallFilters ? performQuery(flagCallsDailyCountQuery(flagCallFilters, trendsQuery, days)) : null,
    ])
    const series = trends.results?.[0] as TrendResult | undefined
    const rows = (flagCalls?.results as [string, number][] | undefined) ?? null
    return { ...withFlagCallCounts(series, rows), labels: series?.labels ?? [] }
}
