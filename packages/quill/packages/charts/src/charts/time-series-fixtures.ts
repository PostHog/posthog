import type { Series } from '../core/types'

export const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

export const SERIES: Series[] = [
    { key: 'visits', label: 'Visits', data: [20, 35, 28, 60, 45, 70, 52] },
    { key: 'signups', label: 'Sign-ups', data: [4, 8, 6, 14, 11, 19, 13] },
    { key: 'activations', label: 'Activations', data: [2, 5, 4, 9, 7, 12, 8] },
]

export const HOURLY_LABELS = Array.from({ length: 24 }, (_, i) => `2025-04-01 ${String(i).padStart(2, '0')}:00:00`)
export const HOURLY_SERIES: Series[] = [
    {
        key: 'visits',
        label: 'Visits',
        data: [12, 9, 7, 6, 8, 14, 22, 35, 48, 55, 60, 64, 62, 58, 54, 50, 46, 44, 40, 36, 30, 24, 18, 14],
    },
]

export const DAILY_LABELS = Array.from({ length: 30 }, (_, i) => {
    const d = new Date(Date.UTC(2025, 2, 15))
    d.setUTCDate(d.getUTCDate() + i)
    return d.toISOString().slice(0, 10)
})
export const DAILY_SERIES: Series[] = [
    {
        key: 'visits',
        label: 'Visits',
        data: DAILY_LABELS.map((_, i) => 40 + Math.round(20 * Math.sin(i / 4))),
    },
]

export const MONTHLY_LABELS = [
    '2024-09-01',
    '2024-10-01',
    '2024-11-01',
    '2024-12-01',
    '2025-01-01',
    '2025-02-01',
    '2025-03-01',
    '2025-04-01',
    '2025-05-01',
    '2025-06-01',
    '2025-07-01',
    '2025-08-01',
]
export const MONTHLY_SERIES: Series[] = [
    { key: 'visits', label: 'Visits', data: [120, 135, 150, 142, 200, 220, 245, 260, 275, 290, 310, 330] },
]

export const NUMERIC_SERIES: Series[] = [
    { key: 'visits', label: 'Visits', data: [1200, 1350, 1280, 1600, 1450, 1700, 1520] },
]
export const PERCENTAGE_SERIES: Series[] = [{ key: 'rate', label: 'Conversion', data: [12, 18, 22, 31, 28, 35, 41] }]
export const PERCENTAGE_SCALED_SERIES: Series[] = [
    { key: 'rate', label: 'Conversion', data: [0.12, 0.18, 0.22, 0.31, 0.28, 0.35, 0.41] },
]
export const CURRENCY_SERIES: Series[] = [
    { key: 'revenue', label: 'Revenue', data: [1200, 1450, 1390, 1820, 1675, 2100, 1990] },
]
export const DURATION_SERIES: Series[] = [
    { key: 'session', label: 'Session length', data: [45, 90, 120, 180, 240, 300, 540] },
]
export const DURATION_MS_SERIES: Series[] = [
    { key: 'latency', label: 'Latency', data: [120, 180, 240, 320, 410, 530, 680] },
]
