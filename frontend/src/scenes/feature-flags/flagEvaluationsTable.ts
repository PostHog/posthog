import { dayjs } from 'lib/dayjs'
import { dateStringToDayJs } from 'lib/utils/dateFilters'

import { FlagEvaluationsModeEnumApi } from '~/generated/core/api.schemas'
import { CompareFilter, DateRange } from '~/queries/schema/schema-general'
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

// The query runners read a missing start as the last 7 days.
const DEFAULT_INSIGHT_DATE_FROM = '-7d'

export function insightReachesPastFlagEvaluationsRetention(
    dateRange: DateRange | null | undefined,
    compareFilter: CompareFilter | null | undefined
): boolean {
    const dateFrom = dateRange?.date_from ?? DEFAULT_INSIGHT_DATE_FROM
    const start = dateStringToDayJs(dateFrom)
    if (!start || reachesPastFlagEvaluationsRetention(dateFrom)) {
        return true
    }
    if (!compareFilter?.compare) {
        return false
    }
    const today = dayjs.utc().startOf('day')
    const comparedPeriodOffset = compareFilter.compare_to
        ? today.diff(dateStringToDayJs(compareFilter.compare_to) ?? today)
        : (dateStringToDayJs(dateRange?.date_to ?? null) ?? dayjs.utc()).diff(start)
    return start.subtract(comparedPeriodOffset, 'millisecond').isBefore(flagEvaluationsRetentionStart())
}
