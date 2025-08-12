import { getFormattedDate } from 'scenes/insights/InsightTooltip/insightTooltipUtils'

import { IntervalType } from '~/types'

describe('getFormattedDate', () => {
    const paramsToExpectedWithNumericInput: [number, IntervalType, string][] = [
        [1, 'minute', '1 minute'],
        [2, 'minute', '2 minutes'],
        [1, 'hour', '1 hour'],
        [2, 'hour', '2 hours'],
        [1, 'day', '1 day'],
        [2, 'day', '2 days'],
        [1, 'week', '1 week'],
        [2, 'week', '2 weeks'],
        [1, 'month', '1 month'],
        [2, 'month', '2 months'],
    ]

    paramsToExpectedWithNumericInput.forEach(([input, interval, expected]) => {
        it(`expects "${expected}" for numeric input "${input}" and interval "${interval}"`, () => {
            expect(getFormattedDate(input, { interval })).toEqual(expected)
        })
    })

    describe('with date string inputs', () => {
        it('formats day intervals correctly', () => {
            expect(getFormattedDate('2024-04-28', { interval: 'day' })).toEqual('28 Apr 2024')
            expect(getFormattedDate('2024-05-12', { interval: 'day' })).toEqual('12 May 2024')
        })

        it('formats hour intervals correctly', () => {
            expect(getFormattedDate('2024-04-28T15:30:00', { interval: 'hour' })).toEqual('28 Apr 2024 15:00')
        })

        it('formats minute intervals correctly', () => {
            expect(getFormattedDate('2024-04-28T15:30:00', { interval: 'minute' })).toEqual('28 Apr 2024 15:30:00')
        })

        it('formats month intervals correctly', () => {
            expect(getFormattedDate('2024-04-28', { interval: 'month' })).toEqual('April 2024')
        })
    })

    describe('with week intervals', () => {
        it('formats full week ranges correctly', () => {
            expect(getFormattedDate('2024-04-28', { interval: 'week' })).toEqual('28 Apr - 4 May 2024')
        })

        it('handles Monday as start of week', () => {
            expect(getFormattedDate('2024-04-24', { interval: 'week', weekStartDay: 1 })).toEqual('22-28 Apr 2024')
        })

        it('handles bounded date ranges within a week', () => {
            expect(
                getFormattedDate('2024-04-25', {
                    interval: 'week',
                    dateRange: { date_from: '2024-04-23', date_to: '2024-04-27' },
                })
            ).toEqual('23-27 Apr 2024')
        })

        it('handles ranges across month boundaries', () => {
            expect(
                getFormattedDate('2024-04-30', {
                    interval: 'week',
                    dateRange: { date_from: '2024-04-29', date_to: '2024-05-05' },
                })
            ).toEqual('29 Apr - 4 May 2024')
        })

        it('handles ranges across year boundaries', () => {
            expect(
                getFormattedDate('2024-12-30', {
                    interval: 'week',
                    dateRange: { date_from: '2024-12-29', date_to: '2025-01-04' },
                })
            ).toEqual('29 Dec 2024 - 4 Jan 2025')
        })

        it('respects date range boundaries', () => {
            expect(
                getFormattedDate('2024-04-30', {
                    interval: 'week',
                    dateRange: { date_from: '2024-04-30', date_to: '2024-05-02' },
                })
            ).toEqual('30 Apr - 2 May 2024')
        })

        it('handles week boundaries within the date range', () => {
            expect(
                getFormattedDate('2024-04-30', {
                    interval: 'week',
                    dateRange: { date_from: '2024-04-01', date_to: '2024-05-29' },
                })
            ).toEqual('28 Apr - 4 May 2024')
        })

        it('handles timezone-specific week boundaries', () => {
            const timestamp = '2024-04-28T00:00:00-07:00' // PDT
            const dateRange = { date_from: '2024-04-28T00:00:00-07:00', date_to: '2024-05-04T23:59:59-07:00' }
            expect(
                getFormattedDate(timestamp, { interval: 'week', dateRange, timezone: 'America/Los_Angeles' })
            ).toEqual('28 Apr - 4 May 2024')
        })
    })

    describe('with timezone handling', () => {
        it('respects the provided timezone', () => {
            // Test that the same timestamp displays differently in different timezones
            const timestamp = '2024-04-28T23:30:00Z'
            expect(getFormattedDate(timestamp, { timezone: 'UTC' })).toEqual('28 Apr 2024')
            expect(getFormattedDate(timestamp, { timezone: 'America/New_York' })).toEqual('28 Apr 2024')
            expect(getFormattedDate(timestamp, { timezone: 'Asia/Tokyo' })).toEqual('29 Apr 2024')
        })

        it('returns the correct week range with provided timezone', () => {
            // Test that the week range is correct in a specific timezone
            const timestamp = '2025-06-15T23:59:59-07:00' // PDT
            expect(
                getFormattedDate(timestamp, {
                    timezone: 'America/Los_Angeles',
                    interval: 'week',
                    dateRange: {
                        date_from: '2025-06-11T00:00:00.000000-07:00',
                        date_to: '2025-06-18T23:59:59.999999-07:00',
                    },
                })
            ).toEqual('15-18 Jun 2025')
        })
    })

    describe('with invalid inputs', () => {
        it('throws an error for invalid date string', () => {
            expect(() => getFormattedDate('invalid-date')).toThrow()
        })

        it('expects undefined string if no inputs', () => {
            expect(getFormattedDate()).toEqual('undefined')
        })
    })
})
