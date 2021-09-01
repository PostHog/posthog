export const intervals = {
    minute: {
        label: 'Minute',
        newDateFrom: 'dStart',
    },
    hour: {
        label: 'Hourly',
        newDateFrom: 'dStart',
    },
    day: {
        label: 'Daily',
        newDateFrom: undefined,
    },
    week: {
        label: 'Weekly',
        newDateFrom: '-30d',
    },
    month: {
        label: 'Monthly',
        newDateFrom: '-90d',
    },
}

export const defaultInterval = intervals.day

export type IntervalKeyType = keyof typeof intervals
