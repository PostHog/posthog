import { dayjs } from 'lib/dayjs'
import { componentsToDayJs, dateStringToComponents, dateStringToDayJs } from 'lib/utils/dateFilters'

import { FlagEvaluationsModeEnumApi } from '~/generated/core/api.schemas'
import { CompareFilter } from '~/queries/schema/schema-general'
import type { TeamPublicType, TeamType } from '~/types'

// Not a root table, so the `posthog.` prefix is part of the name. A team on the Events mode without
// the flag-evaluations-hogql-table flag has no such table. Queries on it fail to resolve for that team.
export const FLAG_EVALUATIONS_TABLE = 'posthog.flag_evaluations'

export const FEATURE_FLAG_CALLED_EVENT = '$feature_flag_called'

const EVENTS_MODE = FlagEvaluationsModeEnumApi.Number0

export function readsFlagEvaluationsTable(team: TeamPublicType | TeamType | null): boolean {
    return (team?.flag_evaluations_mode ?? EVENTS_MODE) !== EVENTS_MODE
}

/**
 * How long a row stays in flag_evaluations. The events table keeps $feature_flag_called forever.
 * Keep it equal to FLAG_EVALUATIONS_TTL_DAYS in posthog/models/flag_evaluations/sql.py.
 */
export const FLAG_EVALUATIONS_RETENTION_DAYS = 90

// Start of the oldest day the table still holds. dateStringToDayJs resolves the ranges this is
// compared to against UTC, so the boundary is UTC too: a browser-local midnight sits hours off it,
// which drops the 90-day preset in a timezone ahead of UTC.
export function flagEvaluationsRetentionStart(): dayjs.Dayjs {
    return dayjs.utc().startOf('day').subtract(FLAG_EVALUATIONS_RETENTION_DAYS, 'day')
}

export function reachesPastFlagEvaluationsRetention(dateFrom: string | null): boolean {
    const parsed = dateStringToDayJs(dateFrom)
    // A null start and "all" are all time, which reaches further than any retained day.
    return !parsed || parsed.isBefore(flagEvaluationsRetentionStart())
}

/** Whether the range an insight ran over, or the period it compares against, starts before the table's oldest day. */
export function insightReachesPastFlagEvaluationsRetention({
    dateFrom,
    resolvedDateRange,
    compareFilter,
}: {
    /** The live editor range, which wins over the saved query's. */
    dateFrom: string | null | undefined
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
    return comparedStart.isBefore(flagEvaluationsRetentionStart())
}
