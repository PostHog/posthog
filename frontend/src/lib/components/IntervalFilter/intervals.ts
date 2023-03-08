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
        label: 'Hour',
        newDateFrom: 'dStart',
    },
    day: {
        label: 'Day',
        newDateFrom: undefined,
    },
    week: {
        label: 'Week',
        newDateFrom: '-30d',
    },
    month: {
        label: 'Month',
        newDateFrom: '-90d',
    },
}
