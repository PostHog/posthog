import { dayjs } from 'lib/dayjs'
import { componentsToDayJs, dateStringToComponents, dateStringToDayJs } from 'lib/utils/dateFilters'

import { FlagEvaluationsModeEnumApi } from '~/generated/core/api.schemas'
import { CompareFilter, ResolvedDateRangeResponse } from '~/queries/schema/schema-general'
import type { TeamPublicType, TeamType } from '~/types'

// Not a root table, so the `posthog.` prefix is part of the name. A team on the Events mode has no
// such table. Queries on it fail to resolve for that team.
export const FLAG_EVALUATIONS_TABLE = 'posthog.flag_evaluations'

export const FEATURE_FLAG_CALLED_EVENT = '$feature_flag_called'

const EVENTS_MODE = FlagEvaluationsModeEnumApi.Number0
const FLAG_EVALUATIONS_ONLY_MODE = FlagEvaluationsModeEnumApi.Number2

export function readsFlagEvaluationsTable(team: TeamPublicType | TeamType | null): boolean {
    return (team?.flag_evaluations_mode ?? EVENTS_MODE) !== EVENTS_MODE
}

/** Whether ingestion writes the team's flag calls to flag_evaluations instead of `events`. */
export function storesFlagCallsOutsideEvents(team: TeamPublicType | TeamType | null): boolean {
    return team?.flag_evaluations_mode === FLAG_EVALUATIONS_ONLY_MODE
}

/**
 * How long PostHog tells customers that flag_evaluations keeps a row. The events table keeps $feature_flag_called
 * forever. Keep it equal to FLAG_EVALUATIONS_RETENTION_DAYS in posthog/models/flag_evaluations/sql.py.
 * FLAG_EVALUATIONS_TTL_DAYS in that file is longer, so the table holds all of a range that starts this many days back.
 */
export const FLAG_EVALUATIONS_RETENTION_DAYS = 90

function dateFormatIn(timezone: string): Intl.DateTimeFormat {
    try {
        return new Intl.DateTimeFormat('en-US', {
            timeZone: timezone,
            year: 'numeric',
            month: '2-digit',
            day: '2-digit',
        })
    } catch {
        // A browser with older timezone data throws a RangeError for a newer zone name, such as Europe/Kyiv.
        return dateFormatIn('UTC')
    }
}

// Intl reads the date in `timezone` without the browser's timezone. dayjs's tz() parses the wall time in the
// browser's timezone. Near a DST change in that timezone, the result can move by an hour or to another day.
function dateInTimezone(instant: dayjs.Dayjs, timezone: string): string {
    const parts = dateFormatIn(timezone).formatToParts(instant.valueOf())
    const part = (type: Intl.DateTimeFormatPartTypes): string => parts.find((p) => p.type === type)?.value ?? ''
    return `${part('year')}-${part('month')}-${part('day')}`
}

export interface FlagCallsInsightResponse {
    timezone?: string | null
    last_refresh?: string | null
    resolved_date_range?: ResolvedDateRangeResponse | null
    resolved_compare_date_range?: ResolvedDateRangeResponse | null
}

function insightTimezone(response: FlagCallsInsightResponse | null | undefined): string {
    return response?.timezone || 'UTC'
}

/** The oldest day the window covers, as a `YYYY-MM-DD` date. Without a response, it is the UTC date as of now. */
export function flagEvaluationsRetentionStartDate(response?: FlagCallsInsightResponse | null): string {
    // The backend resolves the 90-day preset from when the query ran, so a cached result counts back from then.
    const asOf = response?.last_refresh ? dayjs(response.last_refresh) : dayjs()
    // The subtraction runs on a UTC date so that no DST change can shift it.
    return dayjs
        .utc(dateInTimezone(asOf, insightTimezone(response)))
        .subtract(FLAG_EVALUATIONS_RETENTION_DAYS, 'day')
        .format('YYYY-MM-DD')
}

// Start of the oldest day that FLAG_EVALUATIONS_RETENTION_DAYS covers. dateStringToDayJs resolves the ranges this is
// compared to against UTC, so the boundary is UTC too: a browser-local midnight sits hours off it,
// which drops the 90-day preset in a timezone ahead of UTC.
export function flagEvaluationsRetentionStart(): dayjs.Dayjs {
    return dayjs.utc(flagEvaluationsRetentionStartDate())
}

export function reachesPastFlagEvaluationsRetention(dateFrom: string | null): boolean {
    const parsed = dateStringToDayJs(dateFrom)
    // A null start and "all" are all time, which reaches further than any retained day.
    return !parsed || parsed.isBefore(flagEvaluationsRetentionStart())
}

function earliestRead(range: ResolvedDateRangeResponse): dayjs.Dayjs {
    return dayjs(range.read_from ?? range.date_from)
}

// Trends sends the compared range it resolved in the team timezone. The Metric display's change pill gets one
// even though its query has no compareFilter. Stickiness and funnels send none, so this estimates the range in the
// browser's timezone. Across a DST change, the estimate can move the start to the previous day.
function comparedPeriodEarliestRead(
    start: dayjs.Dayjs,
    response: FlagCallsInsightResponse | null | undefined,
    compareFilter: CompareFilter | null | undefined
): dayjs.Dayjs {
    const resolvedCompareDateRange = response?.resolved_compare_date_range
    if (resolvedCompareDateRange?.date_from) {
        return earliestRead(resolvedCompareDateRange)
    }
    if (!compareFilter?.compare) {
        return start
    }
    const compareToComponents = dateStringToComponents(compareFilter.compare_to ?? null)
    return compareToComponents
        ? componentsToDayJs(compareToComponents, start)
        : start.subtract(dayjs(response?.resolved_date_range?.date_to ?? undefined).diff(start), 'millisecond')
}

/**
 * Whether an insight read rows from before the table's oldest day, for its range or the period it compares against.
 * Some queries read before their range starts, such as lifecycle and weekly or monthly active users.
 */
export function insightReachesPastFlagEvaluationsRetention({
    dateFrom,
    response,
    compareFilter,
}: {
    /** The live editor range, which wins over the saved query's. */
    dateFrom: string | null | undefined
    response: FlagCallsInsightResponse | null | undefined
    compareFilter: CompareFilter | null | undefined
}): boolean {
    // All time resolves to the oldest row the table still holds, so the resolved range never shows the cutoff.
    if (dateFrom === 'all') {
        return true
    }
    const resolvedDateRange = response?.resolved_date_range
    if (!resolvedDateRange?.date_from) {
        return false
    }
    const comparedRead = comparedPeriodEarliestRead(dayjs(resolvedDateRange.date_from), response, compareFilter)
    const currentRead = earliestRead(resolvedDateRange)
    const firstRead = currentRead.isBefore(comparedRead) ? currentRead : comparedRead
    // The window covers whole days in the team timezone. This compares dates, not instants. A DST change can
    // repeat midnight. The backend starts the 90-day preset at the first midnight. An instant comparison against
    // the second midnight would show the notice for the preset.
    return dateInTimezone(firstRead, insightTimezone(response)) < flagEvaluationsRetentionStartDate(response)
}
