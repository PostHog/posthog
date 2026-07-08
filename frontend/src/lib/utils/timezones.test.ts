import { shortTimeZone } from 'lib/utils/timezones'

describe('timezones utils', () => {
    test('shortTimezone', () => {
        expect(shortTimeZone('UTC')).toEqual('UTC')
        // All timezones below don't observe DST for simplicity
        expect(shortTimeZone('America/Phoenix')).toEqual('MST')
        expect(shortTimeZone('Europe/Moscow')).toEqual('UTC+3')
        expect(shortTimeZone('Asia/Tokyo')).toEqual('UTC+9')
    })
})
