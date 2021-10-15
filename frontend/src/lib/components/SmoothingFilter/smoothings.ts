export const smoothings = {
    minute: {
        1: {
            label: 'No smoothing',
            intervals: 1,
        },
        5: {
            label: '5 Min',
            intervals: 7,
        },
        60: {
            label: '60 Min',
            intervals: 28,
        },
    },
    hour: {
        1: {
            label: 'No smoothing',
            intervals: 1,
        },
        24: {
            label: '24 Hrs',
            intervals: 28,
        },
    },
    day: {
        1: {
            label: 'No smoothing',
            intervals: 1,
        },
        7: {
            label: '7 Day',
            intervals: 7,
        },
        28: {
            label: '28 Day',
            intervals: 28,
        },
    },
    week: {},
    month: {},
}

export type SmoothingKeyType = keyof typeof smoothings
