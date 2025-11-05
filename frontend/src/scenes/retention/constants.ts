import {
    RETENTION_FIRST_EVER_OCCURRENCE,
    RETENTION_FIRST_OCCURRENCE_MATCHING_FILTERS,
    RETENTION_RECURRING,
} from 'lib/constants'
import { OpUnitType } from 'lib/dayjs'
import { LemonSelectOptions } from 'lib/lemon-ui/LemonSelect'

import { RetentionFilter } from '~/queries/schema/schema-general'
import { RetentionPeriod } from '~/types'

export const dateOptions: RetentionPeriod[] = [RetentionPeriod.Day, RetentionPeriod.Week, RetentionPeriod.Month]

// https://day.js.org/docs/en/durations/creating#list-of-all-available-units
export const dateOptionToTimeIntervalMap: Record<RetentionPeriod, OpUnitType> = {
    Hour: 'h',
    Day: 'd',
    Week: 'w',
    Month: 'M',
}

export const dateOptionPlurals: Record<RetentionPeriod, string> = {
    Hour: 'hours',
    Day: 'days',
    Week: 'weeks',
    Month: 'months',
}

export const retentionOptions: Record<string, string> = {
    [`${RETENTION_FIRST_OCCURRENCE_MATCHING_FILTERS}`]: 'first occurrence matching filters',
    [`${RETENTION_FIRST_EVER_OCCURRENCE}`]: 'first-ever occurrence',
    [`${RETENTION_RECURRING}`]: 'recurringly',
}

export const retentionOptionDescriptions = {
    [`${RETENTION_RECURRING}`]:
        "A user is counted in a cohort for each period in which they perform the action matching the specified filters. A user can belong to multiple cohorts. Example: For a daily insight filtering by 'Browser = Chrome', a user who logs in from Chrome on Monday and Wednesday will be part of both cohorts.",
    [`${RETENTION_FIRST_OCCURRENCE_MATCHING_FILTERS}`]:
        "Users are counted in the cohort when they first perform the action matching your filters. If they did the action before but it didn't match filters, they're still counted when filters first match.",
    [`${RETENTION_FIRST_EVER_OCCURRENCE}`]:
        "Users are only counted if their very first occurrence of this event ever matches your filters. If their first-ever event doesn't match, they're excluded entirely.",
}

export const RETENTION_TIME_WINDOW_MODE_OPTIONS: LemonSelectOptions<NonNullable<RetentionFilter['timeWindowMode']>> = [
    {
        value: 'strict_calendar_dates',
        label: 'strict calendar intervals',
        tooltip: 'Intervals are based on calendar boundaries (e.g., midnight for daily retention)',
    },
    {
        value: '24_hour_windows',
        label: 'rolling 24-hour windows',
        tooltip:
            "Intervals are calculated from each user's first event timestamp (e.g., if a user starts at 11 PM, their 'next day' is 24 hours later at 11 PM)",
    },
]
