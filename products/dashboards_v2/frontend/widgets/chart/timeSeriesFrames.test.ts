import { timeSeriesFromFrames } from './timeSeriesFrames'
import type { DataFrame } from './vizTypes'

const frame = (name: string, times: string[], values: number[]): DataFrame => ({
    name,
    fields: [
        { name: 'time', type: 'time', values: times },
        { name: 'value', type: 'number', values },
    ],
})

describe('timeSeriesFromFrames', () => {
    it('lines up frames on their timestamps in time order and leaves a gap where a frame has no value', () => {
        const { labels, series } = timeSeriesFromFrames([
            frame('a', ['2026-11-02', '2026-11-03'], [2, 3]),
            frame('b', ['2026-11-01', '2026-11-02'], [10, 20]),
        ])

        expect(labels).toEqual(['2026-11-01', '2026-11-02', '2026-11-03'])
        expect(series.map((one) => one.data)).toEqual([
            [NaN, 2, 3],
            [10, 20, NaN],
        ])
    })
})
