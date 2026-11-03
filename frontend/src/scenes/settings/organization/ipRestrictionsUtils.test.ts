import { isIpAllowed, isValidIpAddress, isValidIpOrCidr } from './ipRestrictionsUtils'

describe('IP restriction validation', () => {
    it.each<[string, boolean]>([
        ['203.0.113.4', true],
        ['2001:db8::4', true],
        ['::ffff:203.0.113.4', true],
        ['127.1', false],
        ['192.168.001.001', false],
        ['0x7f000001', false],
        ['3232235777', false],
        ['::ffff:192.168.001.001', false],
        ['203.0.113.4/32', false],
        ['2001:db8::4/128', false],
    ])('validates single address %s', (value, valid) => {
        expect(isValidIpAddress(value)).toBe(valid)
    })

    it.each<[string, boolean]>([
        ['203.0.113.4/24', true],
        ['2001:db8::4/64', true],
        ['203.0.113.4/33', false],
        ['2001:db8::4/129', false],
        ['127.1/8', false],
        ['192.168.001.001/24', false],
        ['203.0.113.4/', false],
    ])('validates restriction %s', (value, valid) => {
        expect(isValidIpOrCidr(value)).toBe(valid)
    })

    it.each<[string, string[], boolean]>([
        ['203.0.113.4', ['203.0.113.0/24'], true],
        ['198.51.100.7', ['203.0.113.0/24'], false],
        ['2001:db8::4', ['2001:db8::/64'], true],
        ['203.0.113.4/32', ['203.0.113.4'], false],
        ['127.1', [], false],
        ['192.168.001.001', ['192.168.1.1'], false],
    ])('tests address %s against its rules', (value, rules, allowed) => {
        expect(isIpAllowed(value, rules)).toBe(allowed)
    })
})
