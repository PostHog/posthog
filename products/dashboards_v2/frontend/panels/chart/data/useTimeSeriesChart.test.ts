import { zoomedTimeRange } from './useTimeSeriesChart'

describe('zoomedTimeRange', () => {
    test.each([
        {
            name: "date labels stay dates and end on the last bucket's final day",
            labels: ['2026-11-01', '2026-11-02', '2026-11-03', '2026-11-04'],
            range: [1, 2],
            interval: undefined,
            expected: { from: '2026-11-02', to: '2026-11-03' },
        },
        {
            name: 'a final monthly bucket ends on its own last day',
            labels: ['2026-01-01', '2026-02-01', '2026-03-01'],
            range: [1, 2],
            interval: 'month',
            expected: { from: '2026-02-01', to: '2026-03-31' },
        },
        {
            name: 'the last bucket ends one step later',
            labels: ['2026-11-01T00:00:00Z', '2026-11-01T01:00:00Z', '2026-11-01T02:00:00Z'],
            range: [1, 2],
            interval: undefined,
            expected: { from: '2026-11-01T01:00:00.000Z', to: '2026-11-01T03:00:00.000Z' },
        },
    ])('$name', ({ labels, range: [start, end], interval, expected }) => {
        expect(zoomedTimeRange(labels, start, end, interval)).toEqual(expected)
    })
})
