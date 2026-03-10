import { getZoomDateRange } from './common'

describe('getZoomDateRange', () => {
    it('zooms from month to day interval for the full month', () => {
        const result = getZoomDateRange('2024-03-15', 'month')
        expect(result).toEqual({
            dateFrom: '2024-03-01',
            dateTo: '2024-03-31',
            interval: 'day',
        })
    })

    it('zooms from week to day interval for a 7-day range', () => {
        const result = getZoomDateRange('2024-03-11', 'week')
        expect(result).toEqual({
            dateFrom: '2024-03-11',
            dateTo: '2024-03-17',
            interval: 'day',
        })
    })

    it('zooms from day to hour interval for the single day', () => {
        const result = getZoomDateRange('2024-03-10', 'day')
        expect(result).toEqual({
            dateFrom: '2024-03-10',
            dateTo: '2024-03-11',
            interval: 'hour',
        })
    })

    it('returns null for hour interval (already finest granularity)', () => {
        expect(getZoomDateRange('2024-03-10', 'hour')).toBeNull()
    })

    it('returns null for invalid date string', () => {
        expect(getZoomDateRange('not-a-date', 'day')).toBeNull()
    })

    it('returns null for empty date string', () => {
        expect(getZoomDateRange('', 'day')).toBeNull()
    })

    it('handles month boundaries correctly for February', () => {
        const result = getZoomDateRange('2024-02-15', 'month')
        expect(result).toEqual({
            dateFrom: '2024-02-01',
            dateTo: '2024-02-29',
            interval: 'day',
        })
    })

    it('handles month boundaries for non-leap-year February', () => {
        const result = getZoomDateRange('2023-02-15', 'month')
        expect(result).toEqual({
            dateFrom: '2023-02-01',
            dateTo: '2023-02-28',
            interval: 'day',
        })
    })

    it('handles week zoom at end of month', () => {
        const result = getZoomDateRange('2024-03-28', 'week')
        expect(result).toEqual({
            dateFrom: '2024-03-28',
            dateTo: '2024-04-03',
            interval: 'day',
        })
    })

    it('returns null for minute interval', () => {
        expect(getZoomDateRange('2024-03-10', 'minute')).toBeNull()
    })

    it('strips timezone from ISO datetime to avoid wrong-month navigation', () => {
        // ISO string with timezone offset: midnight Feb 1 in PST
        // Without stripping, dayjs could shift this to Jan 31 in other timezones
        const result = getZoomDateRange('2026-02-01T00:00:00-08:00', 'month')
        expect(result).toEqual({
            dateFrom: '2026-02-01',
            dateTo: '2026-02-28',
            interval: 'day',
        })
    })
})
