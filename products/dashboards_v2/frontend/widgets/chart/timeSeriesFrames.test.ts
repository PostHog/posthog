import { MAX_REMEMBERED_COLORS, stableSeriesColors, timeSeriesFromFrames } from './timeSeriesFrames'
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

    it('joins a date-only time and a full timestamp that name the same instant', () => {
        const { labels, series } = timeSeriesFromFrames([
            frame('daily', ['2026-11-01', '2026-11-02'], [1, 2], { refId: 'A' }),
            frame('trend', ['2026-11-01T00:00:00.000Z', '2026-11-02T00:00:00.000Z'], [10, 20], { refId: 'B' }),
        ])

        expect(labels).toEqual(['2026-11-01T00:00:00.000Z', '2026-11-02T00:00:00.000Z'])
        expect(series.map((one) => one.data)).toEqual([
            [1, 2],
            [10, 20],
        ])
    })

    it.each([
        { refIds: [undefined], name: 'one series' },
        { refIds: ['A', 'B'], name: 'every target left' },
    ])("keeps the unit's axis when only one unit is left: $name", ({ refIds }) => {
        const { axes } = timeSeriesFromFrames(
            refIds.map((refId) => frame('p95', ['2026-11-01'], [0.2], { refId, unit: 's' }))
        )

        expect(axes).toEqual([{ id: 'left', unit: 's' }])
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

    it('gives frames of one target that share a name their own keys', () => {
        const { series } = timeSeriesFromFrames([
            frame('api', ['2026-11-01'], [1], { refId: 'A' }),
            frame('api', ['2026-11-01'], [2], { refId: 'A' }),
        ])

        expect(series.map((one) => one.key)).toEqual(['A:api', 'A:api#2'])
    })

    it('keeps the colour a collision gave a series when the series it collided with goes away', () => {
        // `B:requests` and `C:value` hash to the same slot of a five-colour palette.
        const requests = frame('requests', ['2026-11-01'], [1], { refId: 'B' })
        const value = frame('value', ['2026-11-01'], [2], { refId: 'C' })
        const assigned = new Map<string, string>()
        const both = timeSeriesFromFrames([requests, value], PALETTE, assigned)
        const withoutB = timeSeriesFromFrames([value], PALETTE, assigned)

        expect(both.series[0].color).not.toEqual(both.series[1].color)
        expect(withoutB.series[0].color).toEqual(both.series[1].color)
    })
})

describe('stableSeriesColors', () => {
    it('gives series that come back together different colours after each was drawn alone', () => {
        // `B:requests` and `C:value` hash to the same slot of a five-colour palette.
        const assigned = new Map<string, string>()
        stableSeriesColors(['B:requests'], PALETTE, assigned)
        stableSeriesColors(['C:value'], PALETTE, assigned)
        const colors = stableSeriesColors(['B:requests', 'C:value'], PALETTE, assigned)

        expect(colors.get('B:requests')).not.toEqual(colors.get('C:value'))
    })

    it('gives a new series a colour no drawn series has, even when older series used every colour', () => {
        const assigned = new Map<string, string>()
        stableSeriesColors(['old-1', 'old-2', 'old-3', 'old-4', 'old-5'], PALETTE, assigned)
        const colors = stableSeriesColors(['B:requests', 'C:value'], PALETTE, assigned)

        expect(colors.get('B:requests')).not.toEqual(colors.get('C:value'))
    })

    it('forgets the oldest colours of series no longer drawn once it remembers too many', () => {
        const assigned = new Map<string, string>()
        for (let refresh = 0; refresh < 3; refresh++) {
            stableSeriesColors(
                Array.from({ length: MAX_REMEMBERED_COLORS }, (_, index) => `${refresh}:${index}`),
                PALETTE,
                assigned
            )
        }

        expect(assigned.size).toBe(MAX_REMEMBERED_COLORS)
        expect(assigned.has('2:0')).toBe(true)
        expect(assigned.has('0:0')).toBe(false)
    })
})
