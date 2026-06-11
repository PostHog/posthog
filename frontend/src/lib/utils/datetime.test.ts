import tk from 'timekeeper'

import { dayjs } from 'lib/dayjs'
import { formatDateTimeRange, getFormattedLastWeekDate } from 'lib/utils/datetime'

describe('datetime utils', () => {
    describe('getFormattedLastWeekDate()', () => {
        it('happy case', () => {
            tk.freeze(new Date(1330688329321))
            expect(getFormattedLastWeekDate()).toEqual('January 13 - March 2, 2012')
            tk.reset()
        })
    })

    describe('formatDateTimeRange()', () => {
        beforeEach(() => {
            tk.freeze(new Date('2025-03-15T12:00:00.000Z'))
        })
        afterEach(() => {
            tk.reset()
        })

        it('formats range in different years with full details', () => {
            const from = dayjs('2024-12-31T14:30:45')
            const to = dayjs('2025-01-01T16:45:30')
            expect(formatDateTimeRange(from, to)).toEqual('December 31, 2024 14:30:45 - January 1, 2025 16:45:30')
        })

        it('formats range in same year but different days', () => {
            const from = dayjs('2024-06-15T09:00:00')
            const to = dayjs('2024-06-20T17:30:00')
            expect(formatDateTimeRange(from, to)).toEqual('June 15, 2024 09:00 - June 20, 17:30')
        })

        it('hides time if both times are midnight', () => {
            const from = dayjs('2024-06-15T00:00:00')
            const to = dayjs('2024-06-20T00:00:00')
            expect(formatDateTimeRange(from, to)).toEqual('June 15, 2024  - June 20')
        })

        it('formats range in same year as current year', () => {
            const from = dayjs('2025-01-10T10:15:00')
            const to = dayjs('2025-02-05T14:20:00')
            expect(formatDateTimeRange(from, to)).toEqual('January 10, 10:15 - February 5, 14:20')
        })

        it('formats range on same day in different year', () => {
            const from = dayjs('2024-08-10T09:30:00')
            const to = dayjs('2024-08-10T18:45:00')
            expect(formatDateTimeRange(from, to)).toEqual('August 10, 2024 09:30 - 18:45')
        })

        it('formats range on same day in current year', () => {
            const from = dayjs('2025-03-15T08:00:00')
            const to = dayjs('2025-03-15T20:00:00')
            expect(formatDateTimeRange(from, to)).toEqual('08:00 - 20:00')
        })

        it('removes seconds when both times have zero seconds on same day', () => {
            const from = dayjs('2025-03-15T10:30:00')
            const to = dayjs('2025-03-15T14:45:00')
            expect(formatDateTimeRange(from, to)).toEqual('10:30 - 14:45')
        })

        it('includes seconds when start time has non-zero seconds', () => {
            const from = dayjs('2025-03-15T10:30:15')
            const to = dayjs('2025-03-15T14:45:00')
            expect(formatDateTimeRange(from, to)).toEqual('10:30:15 - 14:45:00')
        })

        it('includes seconds when end time has non-zero seconds', () => {
            const from = dayjs('2025-03-15T10:30:00')
            const to = dayjs('2025-03-15T14:45:30')
            expect(formatDateTimeRange(from, to)).toEqual('10:30:00 - 14:45:30')
        })

        it('includes seconds when both times have non-zero seconds', () => {
            const from = dayjs('2025-03-15T10:30:15')
            const to = dayjs('2025-03-15T14:45:30')
            expect(formatDateTimeRange(from, to)).toEqual('10:30:15 - 14:45:30')
        })

        it('handles range spanning different days in current year', () => {
            const from = dayjs('2025-03-14T22:00:00')
            const to = dayjs('2025-03-16T02:00:00')
            expect(formatDateTimeRange(from, to)).toEqual('March 14, 22:00 - March 16, 02:00')
        })

        it('handles very short time ranges on same day', () => {
            const from = dayjs('2025-03-15T12:00:00')
            const to = dayjs('2025-03-15T12:01:00')
            expect(formatDateTimeRange(from, to)).toEqual('12:00 - 12:01')
        })
    })
})
