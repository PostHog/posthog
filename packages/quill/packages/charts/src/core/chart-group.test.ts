import {
    buildChartGroupXIndex,
    chartGroupRangeAt,
    chartGroupXAt,
    matchChartGroupRange,
    matchChartGroupX,
    type ChartGroupX,
} from './chart-group'

const HOURLY = ['2024-05-01T10:00:00Z', '2024-05-01T11:00:00Z', '2024-05-01T12:00:00Z']
const FIVE_MIN = Array.from({ length: 36 }, (_, i) => new Date(Date.UTC(2024, 4, 1, 10, i * 5)).toISOString())
// 10:00, 11:00, then nothing until 14:00, 15:00.
const HOURLY_WITH_GAP = ['2024-05-01T10:00:00Z', '2024-05-01T11:00:00Z', '2024-05-01T14:00:00Z', '2024-05-01T15:00:00Z']
const MONTHLY = ['2024-01-01', '2024-02-01', '2024-03-01', '2024-04-01']

function xFrom(labels: string[], index: number): ChartGroupX {
    const x = chartGroupXAt(buildChartGroupXIndex(labels), index)
    if (!x) {
        throw new Error(`no label at ${index}`)
    }
    return x
}

function timeX(iso: string): ChartGroupX {
    return { label: iso, time: Date.parse(iso) }
}

describe('chart group x matching', () => {
    it.each<[string, string[], ChartGroupX, number]>([
        ['same labels match the same index', HOURLY, xFrom(HOURLY, 1), 1],
        ['a finer hover lands in the coarser bucket that contains it', HOURLY, xFrom(FIVE_MIN, 9), 0],
        ['a finer hover at the last bucket start', HOURLY, xFrom(FIVE_MIN, 24), 2],
        ['a coarser hover lands on the finer bucket at its start', FIVE_MIN, xFrom(HOURLY, 1), 12],
        ['before the first bucket matches nothing', HOURLY, timeX('2024-05-01T09:59:00Z'), -1],
        ['inside the last bucket still matches', HOURLY, timeX('2024-05-01T12:59:00Z'), 2],
        ['past the last bucket matches nothing', HOURLY, timeX('2024-05-01T13:00:00Z'), -1],
        ['inside a gap in the data matches nothing', HOURLY_WITH_GAP, timeX('2024-05-01T12:15:00Z'), -1],
        ['a long month still covers its last day', MONTHLY, timeX('2024-01-31T12:00:00Z'), 0],
        ['the bucket before a gap keeps its normal width', HOURLY_WITH_GAP, timeX('2024-05-01T11:59:00Z'), 1],
        ['a categorical label matches by string', ['Mon', 'Tue', 'Wed'], { label: 'Tue', time: null }, 1],
        ['a categorical label missing here matches nothing', ['Mon', 'Tue'], { label: 'Sun', time: null }, -1],
        ['a categorical hover on a time chart matches nothing', HOURLY, { label: 'Tue', time: null }, -1],
    ])('%s', (_name, labels, x, expected) => {
        expect(matchChartGroupX(buildChartGroupXIndex(labels), x)).toBe(expected)
    })

    it('parses offset-free date and date-time labels to the same instant', () => {
        const dateOnly = buildChartGroupXIndex(['2024-05-01', '2024-05-02'])
        expect(matchChartGroupX(dateOnly, xFrom(['2024-05-02T00:00:00', '2024-05-03T00:00:00'], 0))).toBe(1)
    })

    it('reads a compact +HHMM offset as the same instant as +HH:MM', () => {
        const compact = buildChartGroupXIndex(['2024-05-01T12:00:00+0200', '2024-05-01T13:00:00+0200'])
        expect(compact.times).toEqual([Date.parse(HOURLY[0]), Date.parse(HOURLY[1])])
    })

    it('gives a single-label range a length, so it still overlaps the other charts', () => {
        const range = chartGroupRangeAt(buildChartGroupXIndex(['2024-05-01T11:00:00Z']), 0, 0)
        expect(matchChartGroupRange(buildChartGroupXIndex(HOURLY), range)).toEqual({ startIndex: 1, endIndex: 1 })
    })

    it('a single-point chart matches a hover whose bucket contains its point', () => {
        const single = buildChartGroupXIndex(['2024-05-01T10:30:00Z'])
        expect(matchChartGroupX(single, xFrom(HOURLY, 0))).toBe(0)
        expect(matchChartGroupX(single, xFrom(HOURLY, 1))).toBe(-1)
    })

    it('maps a range across intervals by bucket overlap', () => {
        const range = chartGroupRangeAt(buildChartGroupXIndex(HOURLY), 1, 1)
        expect(range).toEqual({
            startLabel: HOURLY[1],
            endLabel: HOURLY[1],
            from: Date.parse('2024-05-01T11:00:00Z'),
            to: Date.parse('2024-05-01T12:00:00Z'),
        })
        expect(matchChartGroupRange(buildChartGroupXIndex(FIVE_MIN), range)).toEqual({ startIndex: 12, endIndex: 23 })
        expect(matchChartGroupRange(buildChartGroupXIndex(['Mon', 'Tue']), range)).toBeNull()
    })

    it('ends the range at the last bucket before missing data, not inside the gap', () => {
        expect(chartGroupRangeAt(buildChartGroupXIndex(HOURLY_WITH_GAP), 1, 1).to).toBe(
            Date.parse('2024-05-01T12:00:00Z')
        )
    })
})
