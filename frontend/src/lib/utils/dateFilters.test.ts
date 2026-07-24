import tk from 'timekeeper'

import { dayjs } from 'lib/dayjs'
import {
    areDatesValidForInterval,
    dateFilterToText,
    dateMapping,
    dateStringToComponents,
    dateStringToDayJs,
    getDefaultInterval,
    is12HoursOrLess,
    isLessThan2Days,
    isValidRelativeOrAbsoluteDate,
} from 'lib/utils/dateFilters'

describe('dateFilters utils', () => {
    describe('dateFilterToText()', () => {
        beforeEach(() => {
            tk.freeze(new Date('2026-06-15T12:00:00.000Z'))
        })
        afterEach(() => {
            tk.reset()
        })

        describe('not formatted', () => {
            it('handles dayjs dates', () => {
                const from = dayjs('2018-04-04T16:00:00.000Z')
                const to = dayjs('2018-04-09T15:05:00.000Z')

                expect(dateFilterToText(from, to, 'custom')).toEqual('April 4 - April 9, 2018')
            })

            it('handles various ranges', () => {
                expect(dateFilterToText('dStart', null, 'default')).toEqual('Today')
                expect(dateFilterToText('2020-01-02', '2020-01-05', 'default')).toEqual('2020-01-02 - 2020-01-05')
                expect(dateFilterToText(null, null, 'default')).toEqual('default')
                expect(dateFilterToText('-24h', null, 'default')).toEqual('Last 24 hours')
                expect(dateFilterToText('-48h', undefined, 'default')).toEqual('Last 48 hours')
                expect(dateFilterToText('-1d', null, 'default')).toEqual('Last 1 day')
                expect(dateFilterToText('-1dStart', '-1dEnd', 'default')).toEqual('Yesterday')
                expect(dateFilterToText('-1mStart', '-1mEnd', 'default')).toEqual('Last month')
            })

            // The frontend DateFilter emits YYYY-MM-DD (without allowTimePrecision) or
            // YYYY-MM-DDTHH:mm:ss (with allowTimePrecision, used by recordings).
            // The AI agent (filter_session_recordings) emits YYYY-MM-DDTHH:mm:ss.SSS.
            // All cross-combinations must display correctly.

            it('handles ISO datetime without milliseconds (frontend DateFilter format)', () => {
                // Both dates as YYYY-MM-DDTHH:mm:ss
                expect(dateFilterToText('2026-02-01T00:00:00', '2026-02-04T23:59:59', 'default')).toEqual(
                    'February 1, 00:00:00 - February 4, 23:59:59'
                )
                // Non-midnight times
                expect(dateFilterToText('2026-02-01T14:30:00', '2026-02-04T18:45:00', 'default')).toEqual(
                    'February 1, 14:30 - February 4, 18:45'
                )
            })

            it('handles ISO datetime with milliseconds (AI agent format)', () => {
                // Both dates as YYYY-MM-DDTHH:mm:ss.SSS
                expect(dateFilterToText('2026-02-01T00:00:00.000', '2026-02-04T23:59:59.999', 'default')).toEqual(
                    'February 1, 00:00:00 - February 4, 23:59:59'
                )
            })

            it('handles mixed datetime formats (frontend × AI agent)', () => {
                // YYYY-MM-DDTHH:mm:ss from + YYYY-MM-DDTHH:mm:ss.SSS to
                expect(dateFilterToText('2026-02-01T00:00:00', '2026-02-04T23:59:59.999', 'default')).toEqual(
                    'February 1, 00:00:00 - February 4, 23:59:59'
                )
                // YYYY-MM-DDTHH:mm:ss.SSS from + YYYY-MM-DDTHH:mm:ss to
                expect(dateFilterToText('2026-02-01T00:00:00.000', '2026-02-04T23:59:59', 'default')).toEqual(
                    'February 1, 00:00:00 - February 4, 23:59:59'
                )
            })

            it('handles plain date + datetime (either direction)', () => {
                // YYYY-MM-DD from + YYYY-MM-DDTHH:mm:ss to
                expect(dateFilterToText('2026-02-01', '2026-02-04T23:59:59', 'default')).toEqual(
                    'February 1, 00:00:00 - February 4, 23:59:59'
                )
                // YYYY-MM-DD from + YYYY-MM-DDTHH:mm:ss.SSS to
                expect(dateFilterToText('2026-02-01', '2026-02-04T23:59:59.999', 'default')).toEqual(
                    'February 1, 00:00:00 - February 4, 23:59:59'
                )
                // YYYY-MM-DDTHH:mm:ss from + YYYY-MM-DD to (both resolve to midnight → times omitted)
                expect(dateFilterToText('2026-02-01T00:00:00', '2026-02-04', 'default')).toEqual(
                    'February 1 - February 4'
                )
                // YYYY-MM-DDTHH:mm:ss.SSS from + YYYY-MM-DD to (both resolve to midnight → times omitted)
                expect(dateFilterToText('2026-02-01T00:00:00.000', '2026-02-04', 'default')).toEqual(
                    'February 1 - February 4'
                )
                // Non-midnight datetime from + YYYY-MM-DD to
                expect(dateFilterToText('2026-02-01T14:30:00', '2026-02-04', 'default')).toEqual(
                    'February 1, 14:30 - February 4, 00:00'
                )
            })

            it('handles same-day datetime range', () => {
                expect(dateFilterToText('2026-02-01T09:00:00', '2026-02-01T17:00:00', 'default')).toEqual(
                    'February 1, 09:00 - 17:00'
                )
            })

            it('can have overridden date options', () => {
                expect(dateFilterToText('-21d', null, 'default', [{ key: 'Last 3 weeks', values: ['-21d'] }])).toEqual(
                    'Last 3 weeks'
                )
            })
        })

        describe('formatted', () => {
            it('handles dayjs dates', () => {
                const from = dayjs('2018-04-04T16:00:00.000Z')
                const to = dayjs('2018-04-09T15:05:00.000Z')

                expect(dateFilterToText(from, to, 'custom', dateMapping, true)).toEqual('April 4 - April 9, 2018')
            })

            it('handles various ranges', () => {
                // 2012-03-02T11:38:49.321Z
                tk.freeze(new Date(1330688329321))
                expect(dateFilterToText('dStart', null, 'default', dateMapping, true)).toEqual('March 2, 2012')
                expect(dateFilterToText('2020-01-02', '2020-01-05', 'default', dateMapping, true)).toEqual(
                    'January 2 - January 5, 2020'
                )
                expect(dateFilterToText(null, null, 'default', dateMapping, true)).toEqual('default')
                expect(dateFilterToText('-24h', null, 'default', dateMapping, true)).toEqual('March 1 - March 2, 2012')
                expect(dateFilterToText('-48h', undefined, 'default', dateMapping, true)).toEqual(
                    'February 29 - March 2, 2012'
                )
                expect(dateFilterToText('-1d', null, 'default', dateMapping, true)).toEqual('March 1 - March 2, 2012')
                expect(dateFilterToText('-1dStart', '-1dEnd', 'default', dateMapping, true)).toEqual('March 1, 2012')
                expect(dateFilterToText('-1mStart', '-1mEnd', 'default', dateMapping, true)).toEqual(
                    'February 1 - February 29, 2012'
                )
                expect(dateFilterToText('-180d', null, 'default', dateMapping, true)).toEqual(
                    'September 4, 2011 - March 2, 2012'
                )
                tk.reset()
            })

            it('can have overridden date options', () => {
                tk.freeze(new Date(1330688329321))
                expect(
                    dateFilterToText(
                        '-21d',
                        null,
                        'default',
                        [{ key: 'Last 3 weeks', values: ['-21d'], getFormattedDate: () => 'custom formatted date' }],
                        true
                    )
                ).toEqual('custom formatted date')
                tk.reset()
            })

            it('can have overridden date format', () => {
                const from = dayjs('2018-04-04T16:00:00.000Z').tz('America/New_York')
                const to = dayjs('2018-04-09T15:05:00.000Z').tz('America/New_York')

                expect(dateFilterToText(from, to, 'custom', dateMapping, true, 'YYYY-MM-DD hh:mm:ss')).toEqual(
                    '2018-04-04 12:00:00 - 2018-04-09 11:05:00'
                )
            })
        })

        describe('week formatting respects weekStartDay', () => {
            // 2012-03-02 is a Friday
            beforeEach(() => {
                tk.freeze(new Date(1330688329321))
            })
            afterEach(() => {
                tk.reset()
            })

            it('This week with Sunday start (default)', () => {
                expect(
                    dateFilterToText('wStart', undefined, 'default', dateMapping, true, undefined, undefined, 0)
                ).toEqual('February 26 - March 2, 2012')
            })

            it('This week with Monday start', () => {
                expect(
                    dateFilterToText('wStart', undefined, 'default', dateMapping, true, undefined, undefined, 1)
                ).toEqual('February 27 - March 2, 2012')
            })

            it('Last week with Sunday start (default)', () => {
                expect(
                    dateFilterToText('-1wStart', '-1wEnd', 'default', dateMapping, true, undefined, undefined, 0)
                ).toEqual('February 19 - February 25, 2012')
            })

            it('Last week with Monday start', () => {
                expect(
                    dateFilterToText('-1wStart', '-1wEnd', 'default', dateMapping, true, undefined, undefined, 1)
                ).toEqual('February 20 - February 26, 2012')
            })
        })
    })

    describe('dateStringToDayJs', () => {
        beforeEach(() => {
            tk.freeze(1330688329321) // randomly chosen time on the 22nd of February 2022
        })
        afterEach(() => {
            tk.reset()
        })

        it('handles various dates', () => {
            expect(dateStringToDayJs('2022-02-22')?.utc(true).toISOString()).toEqual('2022-02-22T00:00:00.000Z')
            expect(dateStringToDayJs('1999-12-31')?.utc(true).toISOString()).toEqual('1999-12-31T00:00:00.000Z')
        })

        it('anchors sub-day units at now, not start of day', () => {
            // frozen: 2012-03-02T11:38:49.321Z. A "-30M" range must mean 30
            // minutes ago — day-anchoring would yield yesterday 23:30 and the
            // metrics/logs "last N minutes" pickers would show a ~24h window.
            expect(dateStringToDayJs('-30M')?.toISOString()).toEqual('2012-03-02T11:08:49.321Z')
            expect(dateStringToDayJs('-5M')?.toISOString()).toEqual('2012-03-02T11:33:49.321Z')
            expect(dateStringToDayJs('-1h')?.toISOString()).toEqual('2012-03-02T10:38:49.321Z')
            expect(dateStringToDayJs('-45s')?.toISOString()).toEqual('2012-03-02T11:38:04.321Z')
        })

        it('handles various units', () => {
            expect(dateStringToDayJs('d')?.utc(true).toISOString()).toEqual('2012-03-02T00:00:00.000Z')
            expect(dateStringToDayJs('m')?.utc(true).toISOString()).toEqual('2012-03-02T00:00:00.000Z')
            expect(dateStringToDayJs('w')?.utc(true).toISOString()).toEqual('2012-03-02T00:00:00.000Z')
            expect(dateStringToDayJs('q')?.utc(true).toISOString()).toEqual('2012-03-02T00:00:00.000Z')
            expect(dateStringToDayJs('y')?.utc(true).toISOString()).toEqual('2012-03-02T00:00:00.000Z')
            expect(dateStringToDayJs('x')).toEqual(null)
        })

        it('handles pluses and minuses', () => {
            expect(dateStringToDayJs('d')?.utc(true).toISOString()).toEqual('2012-03-02T00:00:00.000Z')
            expect(dateStringToDayJs('+d')?.utc(true).toISOString()).toEqual('2012-03-02T00:00:00.000Z')
            expect(dateStringToDayJs('-d')?.utc(true).toISOString()).toEqual('2012-03-02T00:00:00.000Z')

            expect(dateStringToDayJs('1d')?.utc(true).toISOString()).toEqual('2012-03-03T00:00:00.000Z')
            expect(dateStringToDayJs('2d')?.utc(true).toISOString()).toEqual('2012-03-04T00:00:00.000Z')
            expect(dateStringToDayJs('3d')?.utc(true).toISOString()).toEqual('2012-03-05T00:00:00.000Z')
            expect(dateStringToDayJs('33d')?.utc(true).toISOString()).toEqual('2012-04-04T00:00:00.000Z')

            expect(dateStringToDayJs('+1d')?.utc(true).toISOString()).toEqual('2012-03-03T00:00:00.000Z')
            expect(dateStringToDayJs('+2d')?.utc(true).toISOString()).toEqual('2012-03-04T00:00:00.000Z')
            expect(dateStringToDayJs('+3d')?.utc(true).toISOString()).toEqual('2012-03-05T00:00:00.000Z')
            expect(dateStringToDayJs('+33d')?.utc(true).toISOString()).toEqual('2012-04-04T00:00:00.000Z')

            expect(dateStringToDayJs('-1d')?.utc(true).toISOString()).toEqual('2012-03-01T00:00:00.000Z')
            expect(dateStringToDayJs('-2d')?.utc(true).toISOString()).toEqual('2012-02-29T00:00:00.000Z')
            expect(dateStringToDayJs('-3d')?.utc(true).toISOString()).toEqual('2012-02-28T00:00:00.000Z')
            expect(dateStringToDayJs('-33d')?.utc(true).toISOString()).toEqual('2012-01-29T00:00:00.000Z')

            expect(dateStringToDayJs('-33m')?.utc(true).toISOString()).toEqual('2009-06-02T00:00:00.000Z')
            expect(dateStringToDayJs('-33w')?.utc(true).toISOString()).toEqual('2011-07-15T00:00:00.000Z')
            expect(dateStringToDayJs('-33q')?.utc(true).toISOString()).toEqual('2003-12-02T00:00:00.000Z')
            expect(dateStringToDayJs('-33y')?.utc(true).toISOString()).toEqual('1979-03-02T00:00:00.000Z')
        })

        it('handles various start/end values', () => {
            expect(dateStringToDayJs('dStart')?.utc(true).toISOString()).toEqual('2012-03-02T00:00:00.000Z')
            expect(dateStringToDayJs('dEnd')?.utc(true).toISOString()).toEqual('2012-03-02T23:59:59.999Z')
            expect(dateStringToDayJs('wStart')?.utc(true).toISOString()).toEqual('2012-02-26T00:00:00.000Z')
            expect(dateStringToDayJs('wEnd')?.utc(true).toISOString()).toEqual('2012-03-03T23:59:59.999Z')
            expect(dateStringToDayJs('mStart')?.utc(true).toISOString()).toEqual('2012-03-01T00:00:00.000Z')
            expect(dateStringToDayJs('mEnd')?.utc(true).toISOString()).toEqual('2012-03-31T23:59:59.999Z')
            expect(dateStringToDayJs('qStart')?.utc(true).toISOString()).toEqual('2012-01-01T00:00:00.000Z')
            expect(dateStringToDayJs('qEnd')?.utc(true).toISOString()).toEqual('2012-03-31T23:59:59.999Z')
            expect(dateStringToDayJs('yStart')?.utc(true).toISOString()).toEqual('2012-01-01T00:00:00.000Z')
            expect(dateStringToDayJs('yEnd')?.utc(true).toISOString()).toEqual('2012-12-31T23:59:59.999Z')
        })

        it('handles various start/end values with units', () => {
            expect(dateStringToDayJs('1dStart')?.utc(true).toISOString()).toEqual('2012-03-03T00:00:00.000Z')
            expect(dateStringToDayJs('1dEnd')?.utc(true).toISOString()).toEqual('2012-03-03T23:59:59.999Z')

            expect(dateStringToDayJs('-1wStart')?.utc(true).toISOString()).toEqual('2012-02-19T00:00:00.000Z')
            expect(dateStringToDayJs('-1wEnd')?.utc(true).toISOString()).toEqual('2012-02-25T23:59:59.999Z')

            expect(dateStringToDayJs('12mStart')?.utc(true).toISOString()).toEqual('2013-03-01T00:00:00.000Z')
            expect(dateStringToDayJs('12mEnd')?.utc(true).toISOString()).toEqual('2013-03-31T23:59:59.999Z')

            expect(dateStringToDayJs('-4qStart')?.utc(true).toISOString()).toEqual('2011-01-01T00:00:00.000Z')
            expect(dateStringToDayJs('-4qEnd')?.utc(true).toISOString()).toEqual('2011-03-31T23:59:59.999Z')

            expect(dateStringToDayJs('0yStart')?.utc(true).toISOString()).toEqual('2012-01-01T00:00:00.000Z')
            expect(dateStringToDayJs('0yEnd')?.utc(true).toISOString()).toEqual('2012-12-31T23:59:59.999Z')
        })
    })

    describe('getDefaultInterval', () => {
        it('should return days for last 7 days', () => {
            expect(getDefaultInterval('-7d', null)).toEqual('day')
        })

        it('should return hours for last 24 hours', () => {
            expect(getDefaultInterval('-24h', null)).toEqual('hour')
        })

        it('should return days for month to date', () => {
            expect(getDefaultInterval('mStart', null)).toEqual('day')
        })

        it('should return days for week to date', () => {
            expect(getDefaultInterval('wStart', null)).toEqual('day')
        })

        it('should return month for year to date', () => {
            expect(getDefaultInterval('yStart', null)).toEqual('month')
        })

        it('should return month for all time', () => {
            expect(getDefaultInterval('all', null)).toEqual('month')
        })

        it('should handle explicit dates 6 months apart', () => {
            expect(getDefaultInterval('2023-10-01', '2023-04-01')).toEqual('month')
        })
        it('should handle explicit dates a month apart', () => {
            expect(getDefaultInterval('2023-10-01', '2023-09-01')).toEqual('week')
        })
        it('should handle explicit dates a week apart', () => {
            expect(getDefaultInterval('2023-10-01', '2023-09-25')).toEqual('day')
        })
        it('should handle explicit dates a day apart', () => {
            expect(getDefaultInterval('2023-10-02', '2023-10-01')).toEqual('hour')
        })
        it('should handle explicit dates 12 hours apart', () => {
            expect(getDefaultInterval('2023-10-01T18:00:00', '2023-10-01T6:00:00')).toEqual('hour')
        })
        it('should not crash on a non-string date (e.g. numeric URL param)', () => {
            // A value like "?date_from=7" decodes to a number; it must not reach `.match`.
            expect(() => getDefaultInterval(7 as unknown as string, null)).not.toThrow()
            expect(getDefaultInterval(7 as unknown as string, null)).toEqual('day')
        })
    })

    describe('dateStringToComponents', () => {
        it('returns null for non-string values instead of throwing', () => {
            expect(dateStringToComponents(7 as unknown as string)).toBeNull()
            expect(dateStringToComponents(null)).toBeNull()
        })
        it('parses relative date strings', () => {
            expect(dateStringToComponents('-30d')).toEqual({ amount: -30, unit: 'day', clip: '' })
        })
    })

    describe('isValidRelativeOrAbsoluteDate', () => {
        it.each([
            ['-7d', true],
            ['all', true],
            ['2023-10-01', true],
            // bare numbers must be rejected — dayjs() would treat them as epoch timestamps
            ['7', false],
            [7 as unknown as string, false],
            ['not-a-date', false],
        ])('%s -> %s', (date, expected) => {
            expect(isValidRelativeOrAbsoluteDate(date)).toEqual(expected)
        })
    })

    describe('areDatesValidForInterval', () => {
        it('should require interval to be month for all time', () => {
            expect(areDatesValidForInterval('month', 'all', null)).toEqual(true)
            expect(areDatesValidForInterval('week', 'all', null)).toEqual(false)
            expect(areDatesValidForInterval('day', 'all', null)).toEqual(false)
            expect(areDatesValidForInterval('hour', 'all', null)).toEqual(false)
        })
        it('should return false if the dates are one interval apart', () => {
            expect(areDatesValidForInterval('day', '-24h', null)).toEqual(false)
            expect(areDatesValidForInterval('week', '-7d', null)).toEqual(false)
            expect(areDatesValidForInterval('day', '-1d', null)).toEqual(false)
        })
        it('should return true if the dates are two intervals apart', () => {
            expect(areDatesValidForInterval('day', '-48h', null)).toEqual(true)
            expect(areDatesValidForInterval('week', '-14d', null)).toEqual(true)
            expect(areDatesValidForInterval('day', '-2d', null)).toEqual(true)
        })
        it('should return false for hourly if over 2 weeks', () => {
            expect(areDatesValidForInterval('hour', '-15d', null)).toEqual(false)
        })
        it('should support explicit dates', () => {
            expect(areDatesValidForInterval('month', '2023-08-01', '2023-11-01')).toEqual(true)
            expect(areDatesValidForInterval('week', '2023-10-01', '2023-11-01')).toEqual(true)
            expect(areDatesValidForInterval('day', '2023-10-16', '2023-11-01')).toEqual(true)
            expect(areDatesValidForInterval('hour', '2023-11-01T12', '2023-11-01T18')).toEqual(true)
        })
    })

    describe('time ranges', () => {
        it('is less than or equal to 12 hours', () => {
            expect(is12HoursOrLess('-0h')).toBeTruthy()
            expect(is12HoursOrLess('-1h')).toBeTruthy()
            expect(is12HoursOrLess('-12h')).toBeTruthy()
            expect(is12HoursOrLess('-13h')).toBeFalsy()

            expect(is12HoursOrLess('-24h')).toBeFalsy()
            expect(is12HoursOrLess('-30h')).toBeFalsy()
            expect(is12HoursOrLess('-47h')).toBeFalsy()
            expect(is12HoursOrLess('-111h')).toBeFalsy()

            expect(is12HoursOrLess('-1.123h')).toBeFalsy()
            expect(is12HoursOrLess('1.123h')).toBeFalsy()
            expect(is12HoursOrLess('-ab1-13h')).toBeFalsy()
            expect(is12HoursOrLess('-1d')).toBeFalsy()
            expect(is12HoursOrLess('-1w')).toBeFalsy()
            expect(is12HoursOrLess('-1h-2h')).toBeFalsy()
        })

        it('is less than 2 days', () => {
            expect(isLessThan2Days('-0h')).toBeTruthy()
            expect(isLessThan2Days('-1h')).toBeTruthy()
            expect(isLessThan2Days('-12h')).toBeTruthy()
            expect(isLessThan2Days('-24h')).toBeTruthy()
            expect(isLessThan2Days('-30h')).toBeTruthy()
            expect(isLessThan2Days('-47h')).toBeTruthy()

            expect(isLessThan2Days('-48h')).toBeFalsy()
            expect(isLessThan2Days('-49h')).toBeFalsy()
            expect(isLessThan2Days('0h')).toBeFalsy()
            expect(isLessThan2Days('1h')).toBeFalsy()
            expect(isLessThan2Days('48h')).toBeFalsy()
            expect(isLessThan2Days('-13.123h')).toBeFalsy()
            expect(isLessThan2Days('13.123h')).toBeFalsy()
            expect(isLessThan2Days('-ab1-13h')).toBeFalsy()
            expect(isLessThan2Days('-1d-1h')).toBeFalsy()
        })
    })
})
