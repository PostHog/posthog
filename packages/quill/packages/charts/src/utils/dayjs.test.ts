import { dayjs, parseDateInTimezone } from './dayjs'

describe('parseDateInTimezone', () => {
    describe('strings without explicit timezone', () => {
        it('treats date-only strings as wall-clock in the given timezone', () => {
            const result = parseDateInTimezone('2026-03-08', 'America/New_York')
            expect(result.format('YYYY-MM-DD HH:mm')).toBe('2026-03-08 00:00')
            expect(result.format('Z')).toBe('-05:00')
        })

        it('treats datetime strings as wall-clock in the given timezone', () => {
            const result = parseDateInTimezone('2026-03-08 14:30:00', 'America/New_York')
            expect(result.format('YYYY-MM-DD HH:mm')).toBe('2026-03-08 14:30')
        })

        it('parses UTC wall-clock without shifting', () => {
            const result = parseDateInTimezone('2026-03-08 14:30:00', 'UTC')
            expect(result.utc().format('YYYY-MM-DD HH:mm')).toBe('2026-03-08 14:30')
        })
    })

    describe('strings with explicit timezone', () => {
        it.each([
            ['Z suffix', '2026-03-08T14:30:00Z'],
            ['lowercase z suffix', '2026-03-08T14:30:00z'],
            ['+00:00 offset', '2026-03-08T14:30:00+00:00'],
            ['negative offset', '2026-03-08T14:30:00-05:00'],
            ['no colon offset', '2026-03-08T14:30:00+0000'],
        ])('treats %s as a real instant', (_, dateStr) => {
            const result = parseDateInTimezone(dateStr, 'America/New_York')
            expect(result.isValid()).toBe(true)
        })

        it('converts an explicit UTC instant into the requested timezone', () => {
            // Pick a winter date well clear of DST transitions.
            const result = parseDateInTimezone('2026-01-15T14:30:00Z', 'America/New_York')
            expect(result.format('YYYY-MM-DD HH:mm')).toBe('2026-01-15 09:30')
        })
    })

    it('returns invalid Dayjs for unparseable input', () => {
        const result = parseDateInTimezone('not-a-date', 'UTC')
        expect(result.isValid()).toBe(false)
    })

    it('does not depend on the browser timezone for date-only strings', () => {
        const utc = parseDateInTimezone('2026-03-08', 'UTC')
        const tokyo = parseDateInTimezone('2026-03-08', 'Asia/Tokyo')
        expect(utc.format('YYYY-MM-DD')).toBe('2026-03-08')
        expect(tokyo.format('YYYY-MM-DD')).toBe('2026-03-08')
    })
})

describe('dayjs export', () => {
    it('has the timezone plugin extended', () => {
        expect(typeof dayjs.tz).toBe('function')
    })

    it('has the utc plugin extended', () => {
        expect(typeof dayjs.utc).toBe('function')
    })
})
