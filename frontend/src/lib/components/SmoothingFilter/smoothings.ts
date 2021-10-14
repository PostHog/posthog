export const smoothings = {
    '1': {
        label: 'No smoothing',
        intervals: 1,
    },
    '7': {
        label: '7 Day',
        intervals: 7,
    },
    '28': {
        label: '28 Day',
        intervals: 28,
    },
}

export const defaultSmoothing = smoothings['1']

export type SmoothingKeyType = keyof typeof smoothings
