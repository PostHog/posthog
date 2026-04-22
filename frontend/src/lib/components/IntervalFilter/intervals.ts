export type IntervalKeyType = 'minute' | 'hour' | 'day' | 'week' | 'month'

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
        label: 'Minute',
        newDateFrom: 'hStart',
    },
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
