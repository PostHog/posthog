import { RETENTION_FIRST_TIME, RETENTION_RECURRING } from 'lib/constants'
import { OpUnitType } from 'lib/dayjs'

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
    [`${RETENTION_FIRST_TIME}`]: 'for the first time',
    [`${RETENTION_RECURRING}`]: 'recurringly',
}

export const retentionOptionDescriptions = {
    [`${RETENTION_RECURRING}`]:
        "A user is counted in a cohort for each period in which they perform the action matching the specified filters. A user can belong to multiple cohorts. Example: For a daily insight filtering by 'Browser = Chrome', a user who logs in from Chrome on Monday and Wednesday will be part of both cohorts.",
    [`${RETENTION_FIRST_TIME}`]:
        "A user is counted only in the cohort of the first time they performed the action matching the specified filters. This is based on the user's lifetime history. Example: For a monthly insight filtering by 'Browser = Chrome', if a user's first-ever login from Chrome was in April, they will not be included in the cohort for May.",
}
