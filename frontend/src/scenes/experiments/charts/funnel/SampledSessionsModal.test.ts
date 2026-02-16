import { dayjs } from 'lib/dayjs'

import { parseTimestamp } from './SampledSessionsModal'

describe('parseTimestamp', () => {
    it('parses bare datetime string using project timezone', () => {
        // "2026-02-14 00:24:05" in US/Pacific = 08:24:05 UTC
        const result = parseTimestamp('2026-02-14 00:24:05', 'US/Pacific')
        expect(result.utc().format('YYYY-MM-DD HH:mm:ss')).toBe('2026-02-14 08:24:05')
    })

    it('parses bare datetime string in UTC project timezone', () => {
        const result = parseTimestamp('2026-02-14 08:24:05', 'UTC')
        expect(result.utc().format('YYYY-MM-DD HH:mm:ss')).toBe('2026-02-14 08:24:05')
    })

    it('parses bare datetime string in Europe/London timezone', () => {
        // In February, Europe/London is UTC+0
        const result = parseTimestamp('2026-02-14 08:24:05', 'Europe/London')
        expect(result.utc().format('YYYY-MM-DD HH:mm:ss')).toBe('2026-02-14 08:24:05')
    })

    it('parses ISO string with Z suffix directly without timezone conversion', () => {
        const result = parseTimestamp('2026-02-14T08:24:05.123Z', 'US/Pacific')
        expect(result.utc().format('YYYY-MM-DD HH:mm:ss')).toBe('2026-02-14 08:24:05')
    })

    it('parses ISO string with +offset directly without timezone conversion', () => {
        const result = parseTimestamp('2026-02-14T10:24:05+02:00', 'US/Pacific')
        expect(result.utc().format('YYYY-MM-DD HH:mm:ss')).toBe('2026-02-14 08:24:05')
    })

    it('parses ISO string with -offset directly without timezone conversion', () => {
        const result = parseTimestamp('2026-02-14T00:24:05-08:00', 'US/Pacific')
        expect(result.utc().format('YYYY-MM-DD HH:mm:ss')).toBe('2026-02-14 08:24:05')
    })

    it('returns a valid dayjs object', () => {
        const result = parseTimestamp('2026-02-14 00:24:05', 'US/Pacific')
        expect(dayjs.isDayjs(result)).toBe(true)
        expect(result.isValid()).toBe(true)
    })
})
