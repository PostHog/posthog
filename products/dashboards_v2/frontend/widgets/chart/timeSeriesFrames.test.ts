import { timeSeriesFromFrames } from './timeSeriesFrames'
import type { DataFrame } from './vizTypes'

const frame = (
    name: string,
    times: string[],
    values: number[],
    extra: { refId?: string; unit?: string } = {}
): DataFrame => ({
    name,
    ...(extra.refId ? { refId: extra.refId } : {}),
    fields: [
        { name: 'time', type: 'time', values: times },
        { name: 'value', type: 'number', values, ...(extra.unit ? { unit: extra.unit } : {}) },
    ],
})
const PALETTE = ['red', 'green', 'blue', 'orange', 'purple']

describe('timeSeriesFromFrames', () => {
    it('lines up frames on their timestamps and leaves a gap where a frame has no value', () => {
        const { labels, series } = timeSeriesFromFrames([
            frame('a', ['2026-11-01', '2026-11-02'], [1, 2]),
            frame('b', ['2026-11-02', '2026-11-03'], [20, 30]),
        ])

        expect(labels).toEqual(['2026-11-01', '2026-11-02', '2026-11-03'])
        expect(series.map((one) => one.data)).toEqual([
            [1, 2, NaN],
            [NaN, 20, 30],
        ])
    })

    it('draws frames from several targets as their own series, with values that have no unit on their own axis', () => {
        const { labels, series, axes } = timeSeriesFromFrames([
            frame('value', ['2026-11-01T01:00', '2026-11-01T02:00'], [0.2, 0.3], { refId: 'A', unit: 's' }),
            frame('value', ['2026-11-01T00:00', '2026-11-01T01:00'], [5, 7], { refId: 'B' }),
        ])

        expect(labels).toEqual(['2026-11-01T00:00', '2026-11-01T01:00', '2026-11-01T02:00'])
        expect(series.map(({ key, label, data, yAxisId }) => ({ key, label, data, yAxisId }))).toEqual([
            { key: 'A:value', label: 'value', data: [NaN, 0.2, 0.3], yAxisId: undefined },
            { key: 'B:value', label: 'value', data: [5, 7, NaN], yAxisId: 'unit-1' },
        ])
        expect(axes).toEqual([
            { id: 'left', unit: 's' },
            { id: 'unit-1', unit: '' },
        ])
    })

    it("keeps each series' colour when another target returns nothing", () => {
        const latency = frame('p95', ['2026-11-01'], [1], { refId: 'B' })
        const errors = frame('errors', ['2026-11-01'], [2], { refId: 'C' })
        const both = timeSeriesFromFrames(
            [frame('deploys', ['2026-11-01'], [3], { refId: 'A' }), latency, errors],
            PALETTE
        )
        const withoutA = timeSeriesFromFrames([latency, errors], PALETTE)

        expect(withoutA.series.map((one) => one.color)).toEqual(both.series.slice(1).map((one) => one.color))
        expect(new Set(both.series.map((one) => one.color)).size).toBe(3)
    })
})
