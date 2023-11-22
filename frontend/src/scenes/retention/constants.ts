import { RETENTION_FIRST_TIME, RETENTION_RECURRING } from 'lib/constants'
import { OpUnitType } from 'lib/dayjs'

import { RetentionPeriod } from '~/types'

export const dateOptions: RetentionPeriod[] = [
    RetentionPeriod.Hour,
    RetentionPeriod.Day,
    RetentionPeriod.Week,
    RetentionPeriod.Month,
]

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

export const retentionOptions = {
    [RETENTION_FIRST_TIME]: 'for the first time',
    [RETENTION_RECURRING]: 'recurringly',
}

export const retentionOptionDescriptions = {
    [`${RETENTION_RECURRING}`]: 'A user will belong to any cohort where they have performed the event in its Period 0.',
    [`${RETENTION_FIRST_TIME}`]:
        'A user will only belong to the cohort for which they performed the event for the first time.',
}
