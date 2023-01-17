export type IntervalKeyType = 'hour' | 'day' | 'week' | 'month'

export type Intervals = {
    [key in IntervalKeyType]: {
        label: string
        newDateFrom?: string
        disabledReason: string | undefined
    }
}

export const intervals: Intervals = {
    hour: {
        label: 'Hour',
        newDateFrom: 'dStart',
        disabledReason: undefined,
    },
    day: {
        label: 'Day',
        newDateFrom: undefined,
        disabledReason: undefined,
    },
    week: {
        label: 'Week',
        newDateFrom: '-30d',
        disabledReason: undefined,
    },
    month: {
        label: 'Month',
        newDateFrom: '-90d',
        disabledReason: undefined,
    },
}
