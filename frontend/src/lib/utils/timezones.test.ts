import { shortTimeZone, timeZoneLabel } from 'lib/utils/timezones'

describe('timezones utils', () => {
    test('shortTimezone', () => {
        expect(shortTimeZone('UTC')).toEqual('UTC')
        // All timezones below don't observe DST for simplicity
        expect(shortTimeZone('America/Phoenix')).toEqual('MST')
        expect(shortTimeZone('Europe/Moscow')).toEqual('UTC+3')
        expect(shortTimeZone('Asia/Tokyo')).toEqual('UTC+9')
    })

    test('timeZoneLabel', () => {
        expect(timeZoneLabel('America/New_York', -4)).toEqual('America / New York (UTC-4:00)')
        expect(timeZoneLabel('UTC', 0)).toEqual('UTC (UTC±0:00)')
        // Clearing a single-select passes undefined here, which must not throw
        expect(timeZoneLabel(undefined, 0)).toEqual('')
    })
})
