import { isKnownBotIp, isKnownBotUserAgent } from './transformation-functions'

describe('transformation-functions', () => {
    describe('isKnownBotIp', () => {
        it.each([
            ['non-string number', 123, false],
            ['null', null, false],
            ['undefined', undefined, false],
            ['empty string', '', false],
            ['random public IP', '1.2.3.4', false],
            ['exact match from list', '5.39.1.224', true],
            ['IPv4 within CIDR /24 range', '17.22.237.100', true],
            ['IPv4 within CIDR /27 range', '17.241.208.170', true],
            ['IPv4 outside CIDR range', '17.22.237.0', true],
            ['IPv4 just outside CIDR /27', '17.241.208.192', false],
            ['IPv6 within CIDR range', '2400:cb00::1', true],
            ['IPv6 outside known ranges', '2001:db8::1', false],
        ])('%s (%s) -> %s', (_label, input, expected) => {
            expect(isKnownBotIp(input)).toBe(expected)
        })
    })

    describe('isKnownBotUserAgent', () => {
        it.each([
            ['non-string', 42, false],
            ['known bot UA', 'Googlebot/2.1', true],
            ['case-insensitive match', 'MyCustomCrawler/1.0', true],
            ['regular user agent', 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)', false],
        ])('%s (%s) -> %s', (_label, input, expected) => {
            expect(isKnownBotUserAgent(input)).toBe(expected)
        })
    })
})
