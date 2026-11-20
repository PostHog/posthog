import { metricChartInterval } from './metricChart'

describe('metricChart', () => {
    it.each([
        ['a zoomed-in day', '2026-11-09T00:00:00', '2026-11-10T00:00:00', 'hour'],
        ['a picked calendar day', '2026-11-09', '2026-11-09', 'hour'],
        ['a zoomed-in hour', '2026-11-09T13:00:00', '2026-11-09T14:00:00', 'minute'],
        ['the last 3 days', '-3d', null, 'hour'],
        ['the last 7 days', '-7d', null, 'day'],
    ])('picks the bucket size for %s', (_name, dateFrom, dateTo, interval) => {
        expect(metricChartInterval(dateFrom, dateTo)).toBe(interval)
    })
})
