import type { DataFrame } from '../../../query/queryTypes'

const DAYS = ['2026-11-17', '2026-11-18', '2026-11-19', '2026-11-20', '2026-11-21', '2026-11-22', '2026-11-23']

const series = (name: string, values: number[]): DataFrame => ({
    name,
    fields: [
        { name: 'time', type: 'time', values: DAYS },
        { name: 'value', type: 'number', values },
    ],
})

/** Made-up frames every kind of chart can draw, so a sample looks like the chart it stands in for. */
export const SAMPLE_FRAMES: DataFrame[] = [
    series('Pageviews', [34, 27, 41, 38, 52, 46, 61]),
    series('Sign-ups', [12, 16, 14, 22, 19, 26, 31]),
]
