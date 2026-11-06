/**
 * Tests for ClickHouse DateTime Best Effort Parser
 *
 * MAINTENANCE GUIDE:
 * This test file is organized to mirror ClickHouse's test files for easy maintenance.
 * When ClickHouse updates their parsing logic, compare against these source files:
 *
 * Source code: ClickHouse/src/IO/parseDateTimeBestEffort.cpp
 * Wrapper:     ClickHouse/src/Functions/FunctionsConversion.h (isAllRead check at ~line 1464)
 *
 * To check for new test cases:
 *   1. Find all test files: find tests/queries/0_stateless -name "*.sql" | xargs grep -l "parseDateTimeBestEffort"
 *   2. Extract test strings: grep -oE "'[^']+'" <files> | sort -u
 *   3. Compare with this file
 *
 * Note: parseDateTimeBestEffortUS tests (01351, 02381) use a DIFFERENT function
 * that interprets MM-DD-YYYY instead of DD-MM-YYYY. Those are NOT tested here.
 */
import { isValidClickHouseDateTime, parseDateTimeBestEffort } from './clickhouse-datetime-parser'

describe('isValidClickHouseDateTime', () => {
    /**
     * Non-string input handling (not from ClickHouse tests - JavaScript-specific)
     */
    describe('non-string values', () => {
        it('should accept numbers (unix timestamps)', () => {
            expect(isValidClickHouseDateTime(1609459200)).toBe(true)
            expect(isValidClickHouseDateTime(0)).toBe(true)
            expect(isValidClickHouseDateTime(-1000)).toBe(true)
            expect(isValidClickHouseDateTime(1.5)).toBe(true)
        })

        it('should reject non-string, non-number values', () => {
            expect(isValidClickHouseDateTime(null)).toBe(false)
            expect(isValidClickHouseDateTime(undefined)).toBe(false)
            expect(isValidClickHouseDateTime({})).toBe(false)
            expect(isValidClickHouseDateTime([])).toBe(false)
            expect(isValidClickHouseDateTime(true)).toBe(false)
            expect(isValidClickHouseDateTime(false)).toBe(false)
        })
    })

    /**
     * From: 00569_parse_date_time_best_effort.sql
     * Main test file with comprehensive date/time parsing cases
     */
    describe('00569_parse_date_time_best_effort.sql', () => {
        // Invalid cases (return NULL in ClickHouse)
        describe('invalid', () => {
            it.each([
                '0',
                '0000',
                '201',
                '2017/01/32',
                '1970010201:00:00',
                '2017-01-0203:04:05',
                '2017 25 1:2:3',
                '2017 Apr 02 1:2:3 MSK 2017',
                '2017 Apr 02 1:2:3 MSK 2018',
                '25 Jan 2017 1:2:3 Z +0300 OM',
                '25 Jan 2017 1:2:3Z Mo',
                '25 Jan 2017 1:2:3Z Moo',
                'Jun, 11 Feb 2018 06:40:50 +0300',
                '2017 Apr 02 01/02/03 UTC+0300',
            ])('should reject: "%s"', (value) => {
                expect(isValidClickHouseDateTime(value)).toBe(false)
            })
        })

        // Valid cases
        describe('valid', () => {
            it.each([
                '2000-01-01 00:00:00',
                '2000-01-01 01:00:00',
                '02/01/17 010203 MSK',
                '02/01/17 010203 MSK+0100',
                '02/01/17 010203 UTC+0300',
                '02/01/17 010203Z',
                '02/01/1970 010203Z',
                '02/01/70 010203Z',
                '11 Feb 2018 06:40:50 +0300',
                '17 Apr 2000 2 1:2:3',
                '1970/01/02 010203Z',
                '19700102 01:00:00',
                '19700102010203',
                '19700102010203Z',
                '20 2000',
                '2016-01-01',
                '2016-01-01 MSD',
                '2016-01-01MSD',
                '2016-01-01UTC',
                '2016-01-01Z',
                '201601-01',
                '201601-01 MSD',
                '20160101',
                '2017',
                '2017 25 Apr 1:2:3',
                '2017 Apr 01 11:22:33',
                '2017 Apr 02 010203 UTC+0300',
                '2017 Apr 02 01:2:3 UTC+0300',
                '2017 Apr 02 1:02:3',
                '2017 Apr 02 1:2:03',
                '2017 Apr 02 1:2:3',
                '2017 Apr 02 1:2:3 MSK',
                '2017 Apr 02 1:2:3 UTC+0000',
                '2017 Apr 02 1:2:3 UTC+0300',
                '2017 Apr 02 1:2:3 UTC+0400',
                '2017 Apr 02 1:2:33',
                '2017 Apr 02 1:22:33',
                '2017 Apr 02 11:22:33',
                '2017 Apr 2 1:2:3',
                '2017 Jan 02 010203 UTC+0300',
                '2017-01 03:04 MSD Jun',
                '2017-01 03:04:05 MSD Jun',
                '2017-01 MSD Jun',
                '2017-01-02 03:04:05',
                '2017-01-02 03:04:05 -0100',
                '2017-01-02 03:04:05 MSD',
                '2017-01-02 03:04:05 MSD Feb',
                '2017-01-02 03:04:05 MSD Jun',
                '2017-01-02 03:04:05 MSK',
                '2017-01-02 03:04:05+0',
                '2017-01-02 03:04:05+00',
                '2017-01-02 03:04:05+0000',
                '2017-01-02 03:04:05+030',
                '2017-01-02 03:04:05+0300',
                '2017-01-02 03:04:05+1',
                '2017-01-02 03:04:05+300',
                '2017-01-02 03:04:05+900',
                '2017-01-02 03:04:05GMT',
                '2017-01-02T03:04:05',
                '2017-01-02T03:04:05 -0100',
                '2017-01-02T03:04:05+00',
                '2017-01-02T03:04:05+0100',
                '2017-01-02T03:04:05-0100',
                '2017-01-02T03:04:05Z',
                '2017/01/00',
                '2017/01/00 MSD',
                '2017/01/00 MSD Jun',
                '2017/01/01',
                '2017/01/31',
                '201701 02 010203 UTC+0300',
                '201701 MSD Jun',
                '25 Apr 2017 01:02:03',
                '25 Apr 2017 1:2:3',
                '25 Jan 2017 1:2:3',
                '25 Jan 2017 1:2:3 MSK',
                '25 Jan 2017 1:2:3 PM',
                '25 Jan 2017 1:2:3 Z',
                '25 Jan 2017 1:2:3 Z +03:00 PM',
                '25 Jan 2017 1:2:3 Z +0300',
                '25 Jan 2017 1:2:3 Z +0300 PM',
                '25 Jan 2017 1:2:3 Z +03:30 PM',
                '25 Jan 2017 1:2:3 Z PM',
                '25 Jan 2017 1:2:3 Z PM +03:00',
                '25 Jan 2017 1:2:3 Z+03:00',
                '25 Jan 2017 1:2:3 Z+03:00 PM',
                '25 Jan 2017 1:2:3Z',
                '25 Jan 2017 1:2:3Z Mon',
                '25 Jan 2017 1:2:3Z PM',
                'Sun 11 Feb 2018 06:40:50 +0300',
                'Sun, 11 Feb 2018 06:40:50 +0300',
            ])('should accept: "%s"', (value) => {
                expect(isValidClickHouseDateTime(value)).toBe(true)
            })
        })
    })

    /**
     * From: 00813_parse_date_time_best_effort_more.sql
     * European date formats with dots and dashes
     */
    describe('00813_parse_date_time_best_effort_more.sql', () => {
        it.each([
            '24.12.2018',
            '24-12-2018',
            '24.12.18',
            '24-12-18',
            '24-Dec-18',
            '24/DEC/18',
            '24/DEC/2018',
            '01-OCT-2015',
            '24.12.18 010203',
            '24.12.18 01:02:03',
            '24.DEC.18T01:02:03.000+0300',
            '01-September-2018 11:22',
        ])('should accept: "%s"', (value) => {
            expect(isValidClickHouseDateTime(value)).toBe(true)
        })
    })

    /**
     * From: 01123_parse_date_time_best_effort_even_more.sql
     * Day of week with GMT timezone
     */
    describe('01123_parse_date_time_best_effort_even_more.sql', () => {
        it.each(['Thu, 18 Aug 2018 07:22:16 GMT', 'Tue, 16 Aug 2018 07:22:16 GMT'])('should accept: "%s"', (value) => {
            expect(isValidClickHouseDateTime(value)).toBe(true)
        })
    })

    /**
     * From: 01281_parseDateTime64BestEffort.sql
     * DateTime64 parsing including error cases
     */
    describe('01281_parseDateTime64BestEffort.sql', () => {
        describe('invalid', () => {
            it.each([
                'foo',
                'bar',
                '2020-05-14T03:37:03.253184012345678910111213141516171819Z', // too many fractional digits
            ])('should reject: "%s"', (value) => {
                expect(isValidClickHouseDateTime(value)).toBe(false)
            })
        })

        describe('valid', () => {
            it.each([
                '2020-05-14T03:37:03.253184Z',
                '2020-05-14T03:37:03.253184',
                '2020-05-14T03:37:03',
                '2020-05-14 03:37:03',
                '1640649600123',
            ])('should accept: "%s"', (value) => {
                expect(isValidClickHouseDateTime(value)).toBe(true)
            })
        })
    })

    /**
     * From: 01424_parse_date_time_bad_date.sql
     * Invalid decimal number
     */
    describe('01424_parse_date_time_bad_date.sql', () => {
        it('should reject decimal number: "2.55"', () => {
            expect(isValidClickHouseDateTime('2.55')).toBe(false)
        })
    })

    /**
     * From: 01432_parse_date_time_best_effort_timestamp.sql
     * Unix timestamps
     */
    describe('01432_parse_date_time_best_effort_timestamp.sql', () => {
        it.each(['1596752940', '100000000', '20200807'])('should accept: "%s"', (value) => {
            expect(isValidClickHouseDateTime(value)).toBe(true)
        })
    })

    /**
     * From: 01442_date_time_with_params.sql
     * Various datetime formats with AM/PM
     */
    describe('01442_date_time_with_params.sql', () => {
        it.each([
            '2020-05-14T03:37:03',
            '2020-05-14 03:37:03',
            '2020-05-14 11:37:03 AM',
            '2020-05-14 11:37:03 PM',
            '2020-05-14 12:37:03 AM',
            '2020-05-14 12:37:03 PM',
            '2020-05-14T03:37:03.253184',
            '2020-05-14T03:37:03.253184Z',
            '1640649600123',
            'Dec 15, 2021',
        ])('should accept: "%s"', (value) => {
            expect(isValidClickHouseDateTime(value)).toBe(true)
        })
    })

    /**
     * From: 01543_parse_datetime_besteffort_or_null_empty_string.sql
     * Empty/whitespace and AM/PM lowercase
     */
    describe('01543_parse_datetime_besteffort_or_null_empty_string.sql', () => {
        describe('invalid', () => {
            it.each(['', '       ', 'x', '20100', '0100:0100:0000'])('should reject: "%s"', (value) => {
                expect(isValidClickHouseDateTime(value)).toBe(false)
            })
        })

        describe('valid', () => {
            it.each([
                '2010-01-01',
                '2010-01-01 01:01:01',
                '2020-01-01 11:01:01 am',
                '2020-01-01 11:01:01 pm',
                '2020-01-01 12:01:01 am',
                '2020-01-01 12:01:01 pm',
                '2000-01-01 01:01:01',
            ])('should accept: "%s"', (value) => {
                expect(isValidClickHouseDateTime(value)).toBe(true)
            })
        })
    })

    /**
     * From: 02155_parse_date_lowcard_default_throw.sql
     * Short month format
     */
    describe('02155_parse_date_lowcard_default_throw.sql', () => {
        it('should accept: "15-JUL-16"', () => {
            expect(isValidClickHouseDateTime('15-JUL-16')).toBe(true)
        })
    })

    /**
     * From: 02191_parse_date_time_best_effort_more_cases.sql
     * Compact date formats with time separators
     */
    describe('02191_parse_date_time_best_effort_more_cases.sql', () => {
        it.each([
            '20220101-010203',
            '20220101+010203',
            '20220101 010203',
            '20220101T010203',
            '20220101T01:02',
            '20220101-0102',
            '20220101+0102',
            '20220101-010203-01',
            '20220101-010203+0100',
            '20220101-010203-01:00',
        ])('should accept: "%s"', (value) => {
            expect(isValidClickHouseDateTime(value)).toBe(true)
        })
    })

    /**
     * From: 02457_parse_date_time_best_effort.sql
     * Comma as separator
     */
    describe('02457_parse_date_time_best_effort.sql', () => {
        describe('invalid', () => {
            it.each([
                '01/12/2017,',
                '18:31:44,,,, 31/12/2015',
                '18:31:44, 31/12/2015,',
                '01/12/2017, 18:31:44,',
                '01/12/2017, ,,,18:31:44',
                '18:31:44  ,,,,, 31/12/2015',
            ])('should reject: "%s"', (value) => {
                expect(isValidClickHouseDateTime(value)).toBe(false)
            })
        })

        describe('valid', () => {
            it.each([
                '01/12/2017, 18:31:44',
                '01/12/2017,18:31:44',
                '01/12/2017 ,   18:31:44',
                '01/12/2017    ,18:31:44',
                '18:31:44, 31/12/2015',
                '18:31:44  , 31/12/2015',
            ])('should accept: "%s"', (value) => {
                expect(isValidClickHouseDateTime(value)).toBe(true)
            })
        })
    })

    /**
     * From: 02504_parse_datetime_best_effort_calebeaires.sql
     * Pre-epoch dates
     */
    describe('02504_parse_datetime_best_effort_calebeaires.sql', () => {
        it.each(['1969-01-01', '1969-01-01 10:42:00'])('should accept: "%s"', (value) => {
            expect(isValidClickHouseDateTime(value)).toBe(true)
        })
    })

    /**
     * From: 03014_msan_parse_date_time.sql
     * Trailing comma with fixed string (same as 02457 invalid case)
     */
    describe('03014_msan_parse_date_time.sql', () => {
        it('should reject trailing comma: "01/12/2017,"', () => {
            expect(isValidClickHouseDateTime('01/12/2017,')).toBe(false)
        })
    })

    /**
     * From: 03407_parse_date_time_best_effort_unix_timestamp_with_fraction.sql
     * Unix timestamps with fractional seconds
     */
    describe('03407_parse_date_time_best_effort_unix_timestamp_with_fraction.sql', () => {
        // 10-digit timestamps with fractions
        it.each([
            '1744042005.1',
            '1744042005.12',
            '1744042005.123',
            '1744042005.1234',
            '1744042005.12345',
            '1744042005.123456',
            '1744042005.1234567',
            '1744042005.12345678',
            '1744042005.123456789',
        ])('should accept 10-digit with fraction: "%s"', (value) => {
            expect(isValidClickHouseDateTime(value)).toBe(true)
        })

        // 9-digit timestamps with fractions
        it.each([
            '174404200.1',
            '174404200.12',
            '174404200.123',
            '174404200.1234',
            '174404200.12345',
            '174404200.123456',
            '174404200.1234567',
            '174404200.12345678',
            '174404200.123456789',
        ])('should accept 9-digit with fraction: "%s"', (value) => {
            expect(isValidClickHouseDateTime(value)).toBe(true)
        })
    })

    /**
     * From: 03623_datetime64_preepoch_fractional_precision.sql
     * Pre-epoch dates with fractional seconds
     */
    describe('03623_datetime64_preepoch_fractional_precision.sql', () => {
        it.each([
            '1969-01-01 00:00:00.468',
            '1969-07-20 20:17:40.123456',
            '1950-01-01 00:00:00.500',
            '1969-12-31 23:59:59.999',
            '1970-01-01 00:00:00.000',
        ])('should accept: "%s"', (value) => {
            expect(isValidClickHouseDateTime(value)).toBe(true)
        })
    })
})

/**
 * Detailed parsing tests (not organized by file - tests internal behavior)
 */
describe('parseDateTimeBestEffort', () => {
    describe('unix timestamps', () => {
        it('should parse 10-digit unix timestamp', () => {
            const { outcome, fullyConsumed } = parseDateTimeBestEffort('1596752940')
            expect(outcome.valid).toBe(true)
            expect(fullyConsumed).toBe(true)
            if (outcome.valid) {
                expect(outcome.unixSeconds).toBe(1596752940)
            }
        })

        it('should parse 13-digit unix timestamp with milliseconds', () => {
            const { outcome, fullyConsumed } = parseDateTimeBestEffort('1640649600123')
            expect(outcome.valid).toBe(true)
            expect(fullyConsumed).toBe(true)
            if (outcome.valid) {
                expect(outcome.unixSeconds).toBe(1640649600)
                expect(outcome.fractional.value).toBe(123)
                expect(outcome.fractional.digits).toBe(3)
            }
        })

        it('should parse unix timestamp with fractional seconds', () => {
            const { outcome, fullyConsumed } = parseDateTimeBestEffort('1744042005.123456')
            expect(outcome.valid).toBe(true)
            expect(fullyConsumed).toBe(true)
            if (outcome.valid) {
                expect(outcome.unixSeconds).toBe(1744042005)
                expect(outcome.fractional.value).toBe(123456)
                expect(outcome.fractional.digits).toBe(6)
            }
        })
    })

    describe('ISO 8601 parsing', () => {
        it('should parse ISO datetime with Z timezone', () => {
            const { outcome, fullyConsumed } = parseDateTimeBestEffort('2020-05-14T03:37:03Z')
            expect(outcome.valid).toBe(true)
            expect(fullyConsumed).toBe(true)
            if (outcome.valid) {
                expect(outcome.unixSeconds).toBe(1589427423)
            }
        })

        it('should parse ISO datetime with fractional seconds', () => {
            const { outcome, fullyConsumed } = parseDateTimeBestEffort('2020-05-14T03:37:03.253184Z')
            expect(outcome.valid).toBe(true)
            expect(fullyConsumed).toBe(true)
            if (outcome.valid) {
                expect(outcome.unixSeconds).toBe(1589427423)
                expect(outcome.fractional.value).toBe(253184)
                expect(outcome.fractional.digits).toBe(6)
            }
        })
    })

    describe('compact formats', () => {
        it('should parse YYYYMMDD', () => {
            const { outcome, fullyConsumed } = parseDateTimeBestEffort('20200514')
            expect(outcome.valid).toBe(true)
            expect(fullyConsumed).toBe(true)
            if (outcome.valid) {
                const date = new Date(outcome.unixSeconds * 1000)
                expect(date.getFullYear()).toBe(2020)
                expect(date.getMonth()).toBe(4)
                expect(date.getDate()).toBe(14)
            }
        })

        it('should parse YYYYMMDDhhmmss', () => {
            const { outcome, fullyConsumed } = parseDateTimeBestEffort('20200514033703')
            expect(outcome.valid).toBe(true)
            expect(fullyConsumed).toBe(true)
            if (outcome.valid) {
                const date = new Date(outcome.unixSeconds * 1000)
                expect(date.getFullYear()).toBe(2020)
                expect(date.getMonth()).toBe(4)
                expect(date.getDate()).toBe(14)
                expect(date.getHours()).toBe(3)
                expect(date.getMinutes()).toBe(37)
                expect(date.getSeconds()).toBe(3)
            }
        })
    })

    describe('two-digit year handling', () => {
        it('should interpret YY >= 70 as 19YY', () => {
            const { outcome, fullyConsumed } = parseDateTimeBestEffort('02/01/70')
            expect(outcome.valid).toBe(true)
            expect(fullyConsumed).toBe(true)
            if (outcome.valid) {
                const date = new Date(outcome.unixSeconds * 1000)
                expect(date.getFullYear()).toBe(1970)
            }
        })

        it('should interpret YY < 70 as 20YY', () => {
            const { outcome, fullyConsumed } = parseDateTimeBestEffort('02/01/17')
            expect(outcome.valid).toBe(true)
            expect(fullyConsumed).toBe(true)
            if (outcome.valid) {
                const date = new Date(outcome.unixSeconds * 1000)
                expect(date.getFullYear()).toBe(2017)
            }
        })
    })

    describe('timezone offset handling', () => {
        it('should apply positive timezone offset', () => {
            const { outcome, fullyConsumed } = parseDateTimeBestEffort('2017-01-02 03:04:05+0300')
            expect(outcome.valid).toBe(true)
            expect(fullyConsumed).toBe(true)
            if (outcome.valid) {
                const date = new Date(outcome.unixSeconds * 1000)
                expect(date.getUTCHours()).toBe(0)
                expect(date.getUTCMinutes()).toBe(4)
            }
        })

        it('should apply negative timezone offset', () => {
            const { outcome, fullyConsumed } = parseDateTimeBestEffort('2017-01-02 03:04:05 -0100')
            expect(outcome.valid).toBe(true)
            expect(fullyConsumed).toBe(true)
            if (outcome.valid) {
                const date = new Date(outcome.unixSeconds * 1000)
                expect(date.getUTCHours()).toBe(4)
                expect(date.getUTCMinutes()).toBe(4)
            }
        })

        it('should handle MSK timezone (+3)', () => {
            const { outcome, fullyConsumed } = parseDateTimeBestEffort('2017-01-02 03:04:05 MSK')
            expect(outcome.valid).toBe(true)
            expect(fullyConsumed).toBe(true)
            if (outcome.valid) {
                const date = new Date(outcome.unixSeconds * 1000)
                expect(date.getUTCHours()).toBe(0)
            }
        })

        it('should handle MSD timezone (+4)', () => {
            const { outcome, fullyConsumed } = parseDateTimeBestEffort('2017-01-02 03:04:05 MSD')
            expect(outcome.valid).toBe(true)
            expect(fullyConsumed).toBe(true)
            if (outcome.valid) {
                const date = new Date(outcome.unixSeconds * 1000)
                expect(date.getUTCHours()).toBe(23)
            }
        })
    })

    describe('AM/PM handling', () => {
        it('should handle PM (add 12 hours when hour < 12)', () => {
            const { outcome, fullyConsumed } = parseDateTimeBestEffort('25 Jan 2017 1:2:3 PM')
            expect(outcome.valid).toBe(true)
            expect(fullyConsumed).toBe(true)
            if (outcome.valid) {
                const date = new Date(outcome.unixSeconds * 1000)
                expect(date.getHours()).toBe(13)
            }
        })

        it('should handle 12 PM (stays at 12)', () => {
            const { outcome, fullyConsumed } = parseDateTimeBestEffort('25 Jan 2017 12:4:5 PM')
            expect(outcome.valid).toBe(true)
            expect(fullyConsumed).toBe(true)
            if (outcome.valid) {
                const date = new Date(outcome.unixSeconds * 1000)
                expect(date.getHours()).toBe(12)
            }
        })

        it('should handle 12 AM (becomes 0)', () => {
            const { outcome, fullyConsumed } = parseDateTimeBestEffort('25 Jan 2017 12:4:5 AM')
            expect(outcome.valid).toBe(true)
            expect(fullyConsumed).toBe(true)
            if (outcome.valid) {
                const date = new Date(outcome.unixSeconds * 1000)
                expect(date.getHours()).toBe(0)
            }
        })
    })

    describe('date validation', () => {
        it('should reject Feb 30', () => {
            const { outcome } = parseDateTimeBestEffort('2020-02-30')
            expect(outcome.valid).toBe(false)
        })

        it('should accept Feb 29 on leap year', () => {
            const { outcome, fullyConsumed } = parseDateTimeBestEffort('2020-02-29')
            expect(outcome.valid).toBe(true)
            expect(fullyConsumed).toBe(true)
        })

        it('should reject Feb 29 on non-leap year', () => {
            const { outcome } = parseDateTimeBestEffort('2019-02-29')
            expect(outcome.valid).toBe(false)
        })

        it('should reject day 32', () => {
            const { outcome } = parseDateTimeBestEffort('2017/01/32')
            expect(outcome.valid).toBe(false)
        })

        it('should reject month 13', () => {
            const { outcome } = parseDateTimeBestEffort('2017-13-01')
            expect(outcome.valid).toBe(false)
        })
    })

    describe('month/day swap when month > 12', () => {
        it('should swap month and day when first value > 12', () => {
            const { outcome, fullyConsumed } = parseDateTimeBestEffort('24/12/2018')
            expect(outcome.valid).toBe(true)
            expect(fullyConsumed).toBe(true)
            if (outcome.valid) {
                const date = new Date(outcome.unixSeconds * 1000)
                expect(date.getMonth()).toBe(11)
                expect(date.getDate()).toBe(24)
            }
        })
    })
})

/**
 * Comparison with JavaScript's Date parser
 */
describe('comparison with new Date()', () => {
    describe('formats ClickHouse accepts but new Date() rejects', () => {
        it.each([
            '1640649600',
            '1640649600123',
            '20240115',
            '20240115143022',
            '15.01.2024',
            '15-01-2024',
            '24/DEC/2018',
        ])('should accept "%s" (which new Date() rejects)', (value) => {
            expect(isValidClickHouseDateTime(value)).toBe(true)
        })
    })
})
