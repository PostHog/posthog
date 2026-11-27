import { zoomedTimeRange } from './useTimeSeriesChart'

describe('zoomedTimeRange', () => {
    test.each([
        {
            name: 'date labels stay dates and end after the last bucket',
            labels: ['2026-11-01', '2026-11-02', '2026-11-03', '2026-11-04'],
            range: [1, 2],
            expected: { from: '2026-11-02', to: '2026-11-04' },
        },
        {
            name: 'the last bucket ends one step later',
            labels: ['2026-11-01T00:00:00Z', '2026-11-01T01:00:00Z', '2026-11-01T02:00:00Z'],
            range: [1, 2],
            expected: { from: '2026-11-01T01:00:00.000Z', to: '2026-11-01T03:00:00.000Z' },
        },
    ])('$name', ({ labels, range: [start, end], expected }) => {
        expect(zoomedTimeRange(labels, start, end)).toEqual(expected)
    })
})
