import type { IntervalType } from '~/types'

// Derived from IntervalType so the compiler forces a picker decision when the schema gains an interval.
// 'second' is intentionally not selectable in the UI.
export type IntervalKeyType = Exclude<IntervalType, 'second'>

export type Intervals = {
    [key in IntervalKeyType]: {
        label: string
        newDateFrom?: string
        disabledReason?: string
        hidden?: boolean
    }
}

export const intervals: Intervals = {
    minute: {
        label: 'minute',
        newDateFrom: 'hStart',
    },
    hour: {
        label: 'hour',
        newDateFrom: 'dStart',
    },
    day: {
        label: 'day',
        newDateFrom: undefined,
    },
    week: {
        label: 'week',
        newDateFrom: '-30d',
    },
    month: {
        label: 'month',
        newDateFrom: '-90d',
    },
    quarter: {
        label: 'quarter',
        newDateFrom: '-3y',
        hidden: true,
    },
    year: {
        label: 'year',
        newDateFrom: '-5y',
        hidden: true,
    },
}
