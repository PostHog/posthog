export type IntervalKeyType = 'hour' | 'day' | 'week' | 'month'

export type Intervals = {
    [key in IntervalKeyType]: {
        label: string
        newDateFrom?: string
        disabledReason?: string
    }
}

export const intervals: Intervals = {
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
}
