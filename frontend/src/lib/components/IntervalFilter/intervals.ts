export const intervals = {
    minute: {
        label: 'Minute',
        newDateFrom: 'dStart',
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

export const defaultInterval = intervals.day

export type IntervalKeyType = keyof typeof intervals
