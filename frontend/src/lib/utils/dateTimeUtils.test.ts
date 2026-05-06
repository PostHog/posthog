import { dayjs } from 'lib/dayjs'

import { parseDateInTimezone } from './dateTimeUtils'

describe('parseDateInTimezone', () => {
    describe('date-only strings', () => {
        it.each([
            ['UTC', '+00:00'],
            ['America/Los_Angeles', '-07:00'],
            ['Asia/Tokyo', '+09:00'],
            ['Europe/Berlin', '+02:00'],
        ])('treats "2026-05-05" as wall-clock midnight in project tz %s', (timezone, expectedOffset) => {
            const out = parseDateInTimezone('2026-05-05', timezone)
            expect(out.format('YYYY-MM-DD HH:mm Z')).toEqual(`2026-05-05 00:00 ${expectedOffset}`)
        })

        it('returns the same calendar day across browser timezones (no DST drift)', () => {
            // The chart x-axis renders this with a 'D MMM' or 'MMM D' format.
            // Across DST boundaries and across browser timezones, the calendar day
            // for a date-only string must not shift by ±1 day.
            const out = parseDateInTimezone('2026-03-08', 'America/Los_Angeles')
            expect(out.format('D MMM YYYY')).toEqual('8 Mar 2026')
        })
    })

    describe('strings with explicit timezone offset', () => {
        it('treats Z-suffixed timestamps as real instants and converts to project tz', () => {
            // 2024-04-28 23:30 UTC = 2024-04-29 08:30 in Tokyo.
            const out = parseDateInTimezone('2024-04-28T23:30:00Z', 'Asia/Tokyo')
            expect(out.format('YYYY-MM-DD HH:mm Z')).toEqual('2024-04-29 08:30 +09:00')
        })

        it('treats +HH:MM offsets as real instants', () => {
            // 2024-04-28 00:00 -07:00 = 2024-04-28 07:00 UTC = 2024-04-28 16:00 Tokyo.
            const out = parseDateInTimezone('2024-04-28T00:00:00-07:00', 'Asia/Tokyo')
            expect(out.format('YYYY-MM-DD HH:mm Z')).toEqual('2024-04-28 16:00 +09:00')
        })
    })

    describe('invalid inputs', () => {
        it('returns an invalid Dayjs for unparseable strings instead of throwing', () => {
            const out = parseDateInTimezone('not-a-date', 'UTC')
            expect(dayjs.isDayjs(out)).toBe(true)
            expect(out.isValid()).toBe(false)
        })
    })
})
