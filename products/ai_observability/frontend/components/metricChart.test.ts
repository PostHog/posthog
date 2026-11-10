import { metricChartBucketRange, metricChartInterval } from './metricChart'

describe('metricChart', () => {
    it.each([
        ['a day bucket', '2026-11-09', '2026-11-09', 'day', '2026-11-09T00:00:00', '2026-11-09T23:59:59'],
        ['a dragged span of days', '2026-11-03', '2026-11-05', 'day', '2026-11-03T00:00:00', '2026-11-05T23:59:59'],
        [
            'a minute bucket',
            '2026-11-09 13:05:00',
            '2026-11-09 13:05:00',
            'minute',
            '2026-11-09T13:05:00',
            '2026-11-09T13:05:59',
        ],
    ] as const)('covers %s with its own date range', (_name, start, end, interval, dateFrom, dateTo) => {
        expect(metricChartBucketRange(start, end, interval)).toEqual({ dateFrom, dateTo })
    })

    it.each([
        ['a zoomed-in day', '2026-11-09T00:00:00', '2026-11-09T23:59:59', 'hour'],
        ['a zoomed-in hour', '2026-11-09T13:00:00', '2026-11-09T13:59:59', 'minute'],
        ['the last 3 days', '-3d', null, 'hour'],
        ['the last 7 days', '-7d', null, 'day'],
    ])('picks the bucket size for %s', (_name, dateFrom, dateTo, interval) => {
        expect(metricChartInterval(dateFrom, dateTo)).toBe(interval)
    })
})
