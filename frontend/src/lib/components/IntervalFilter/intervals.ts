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
}
