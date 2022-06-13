import { LemonSelectOptions } from '@posthog/lemon-ui'
import { range } from 'lib/utils'

export const intervalOptions: LemonSelectOptions = range(1, 13).reduce(
    (acc, x) => ({
        ...acc,
        [x]: { label: x },
    }),
    {}
)

export const frequencyOptions: LemonSelectOptions = {
    daily: { label: 'days' },
    weekly: { label: 'weeks' },
    monthly: { label: 'months' },
}

export const weekdayOptions: LemonSelectOptions = {
    monday: { label: 'monday' },
    tuesday: { label: 'tuesday' },
    wednesday: { label: 'wednesday' },
    thursday: { label: 'thursday' },
    friday: { label: 'friday' },
    saturday: { label: 'saturday' },
    sunday: { label: 'sunday' },
}

export const monthlyWeekdayOptions: LemonSelectOptions = {
    day: { label: 'day' },
    ...weekdayOptions,
}

export const bysetposOptions: LemonSelectOptions = {
    '1': { label: 'first' },
    '2': { label: 'second' },
    '3': { label: 'third' },
    '4': { label: 'fourth' },
    '-1': { label: 'last' },
}

export const timeOptions: LemonSelectOptions = range(0, 24).reduce(
    (acc, x) => ({
        ...acc,
        [String(x)]: { label: `${String(x).padStart(2, '0')}:00` },
    }),
    {}
)
