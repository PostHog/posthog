import { dayjs } from 'lib/dayjs'
import { componentsToDayJs, dateStringToComponents, dateStringToDayJs } from 'lib/utils/dateFilters'

import { FlagEvaluationsModeEnumApi } from '~/generated/core/api.schemas'
import { CompareFilter } from '~/queries/schema/schema-general'
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

// Intl reads the date in `timezone` without the browser's timezone. dayjs's tz() parses the wall time in the
// browser's timezone. Near a DST change in that timezone, the result can move by an hour or to another day.
function dateInTimezone(instant: dayjs.Dayjs, timezone: string): string {
    const parts = new Intl.DateTimeFormat('en-US', {
        timeZone: timezone,
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
    }).formatToParts(instant.valueOf())
    const part = (type: Intl.DateTimeFormatPartTypes): string => parts.find((p) => p.type === type)?.value ?? ''
    return `${part('year')}-${part('month')}-${part('day')}`
}

export function flagEvaluationsRetentionStartDate(timezone: string): string {
    // The subtraction runs on a UTC date so that no DST change can shift it.
    return dayjs
        .utc(dateInTimezone(dayjs(), timezone))
        .subtract(FLAG_EVALUATIONS_RETENTION_DAYS, 'day')
        .format('YYYY-MM-DD')
}

// Start of the oldest day that FLAG_EVALUATIONS_RETENTION_DAYS covers. dateStringToDayJs resolves the ranges this is
// compared to against UTC, so the boundary is UTC too: a browser-local midnight sits hours off it,
// which drops the 90-day preset in a timezone ahead of UTC.
export function flagEvaluationsRetentionStart(): dayjs.Dayjs {
    return dayjs.utc(flagEvaluationsRetentionStartDate('UTC'))
}

export function reachesPastFlagEvaluationsRetention(dateFrom: string | null): boolean {
    const parsed = dateStringToDayJs(dateFrom)
    // A null start and "all" are all time, which reaches further than any retained day.
    return !parsed || parsed.isBefore(flagEvaluationsRetentionStart())
}

/** Whether the range an insight ran over, or the period it compares against, starts before the table's oldest day. */
export function insightReachesPastFlagEvaluationsRetention({
    dateFrom,
    timezone,
    resolvedDateRange,
    compareFilter,
}: {
    /** The live editor range, which wins over the saved query's. */
    dateFrom: string | null | undefined
    /** The team timezone the backend resolved the range in. */
    timezone: string
    resolvedDateRange: { date_from?: string | null; date_to?: string | null } | null | undefined
    compareFilter: CompareFilter | null | undefined
}): boolean {
    // All time resolves to the oldest row the table still holds, so the resolved range never shows the cutoff.
    if (dateFrom === 'all') {
        return true
    }
    if (!resolvedDateRange?.date_from) {
        return false
    }
    const start = dayjs(resolvedDateRange.date_from)
    const compareToComponents = compareFilter?.compare ? dateStringToComponents(compareFilter.compare_to ?? null) : null
    const comparedStart = !compareFilter?.compare
        ? start
        : compareToComponents
          ? componentsToDayJs(compareToComponents, start)
          : start.subtract(dayjs(resolvedDateRange.date_to ?? undefined).diff(start), 'millisecond')
    // The window covers whole days in the team timezone. This compares dates, not instants, because a DST change
    // can repeat midnight. The backend resolves the 90-day preset to the first midnight, and a boundary at the
    // second midnight would flag the preset.
    return dateInTimezone(comparedStart, timezone) < flagEvaluationsRetentionStartDate(timezone)
}
