export const intervals = {
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

export type IntervalKeyType = keyof typeof intervals
