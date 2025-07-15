import { isIPAddressInRange } from '../stl/ip' // Adjust the import path as needed

describe('isIPAddressInRange', () => {
    // IPv4 Tests
    describe('IPv4', () => {
        test('exact match', () => {
            expect(isIPAddressInRange('192.168.1.1', '192.168.1.1/32')).toBe(true)
        })

        test('within range - small subnet', () => {
            expect(isIPAddressInRange('192.168.1.5', '192.168.1.0/24')).toBe(true)
        })

        test('within range - large subnet', () => {
            expect(isIPAddressInRange('192.168.1.5', '192.0.0.0/8')).toBe(true)
        })

        test('outside range', () => {
            expect(isIPAddressInRange('192.168.1.5', '192.168.2.0/24')).toBe(false)
        })

        test('edge case - broadcast address', () => {
            expect(isIPAddressInRange('192.168.1.255', '192.168.1.0/24')).toBe(true)
        })

        test('edge case - network address', () => {
            expect(isIPAddressInRange('192.168.1.0', '192.168.1.0/24')).toBe(true)
        })

        test('edge case - full internet range', () => {
            expect(isIPAddressInRange('8.8.8.8', '0.0.0.0/0')).toBe(true)
        })

        test('edge case - single IP mask', () => {
            expect(isIPAddressInRange('192.168.1.1', '192.168.1.1/32')).toBe(true)
            expect(isIPAddressInRange('192.168.1.2', '192.168.1.1/32')).toBe(false)
        })
    })

    // IPv6 Tests
    describe('IPv6', () => {
        test('exact match', () => {
            expect(isIPAddressInRange('2001:db8::1', '2001:db8::1/128')).toBe(true)
        })

        test('within range - small subnet', () => {
            expect(isIPAddressInRange('2001:db8::1:5', '2001:db8::1:0/112')).toBe(true)
        })

        test('within range - large subnet', () => {
            expect(isIPAddressInRange('2001:db8::1:5', '2001:db8::/32')).toBe(true)
        })

        test('outside range', () => {
            expect(isIPAddressInRange('2001:db8:1::5', '2001:db8:2::/48')).toBe(false)
        })

        test('edge case - full subnet range', () => {
            expect(isIPAddressInRange('2001:db8::ffff', '2001:db8::/64')).toBe(true)
        })

        test('edge case - network address', () => {
            expect(isIPAddressInRange('2001:db8::', '2001:db8::/64')).toBe(true)
        })

        test('edge case - full internet range', () => {
            expect(isIPAddressInRange('2001:db8::1', '::/0')).toBe(true)
        })

        test('handles abbreviated IPv6', () => {
            expect(isIPAddressInRange('2001:db8::1', '2001:db8:0:0:0:0:0:0/64')).toBe(true)
            expect(isIPAddressInRange('2001:db8:0:0:0:0:0:1', '2001:db8::/64')).toBe(true)
        })

        test('edge case - single IP mask', () => {
            expect(isIPAddressInRange('2001:db8::1', '2001:db8::1/128')).toBe(true)
            expect(isIPAddressInRange('2001:db8::2', '2001:db8::1/128')).toBe(false)
        })
    })

    // Invalid input tests
    describe('Invalid inputs', () => {
        test('null or undefined inputs', () => {
            expect(isIPAddressInRange(null as any, '192.168.1.0/24')).toBe(false)
            expect(isIPAddressInRange('192.168.1.1', null as any)).toBe(false)
            expect(isIPAddressInRange(undefined as any, '192.168.1.0/24')).toBe(false)
            expect(isIPAddressInRange('192.168.1.1', undefined as any)).toBe(false)
        })

        test('empty strings', () => {
            expect(isIPAddressInRange('', '192.168.1.0/24')).toBe(false)
            expect(isIPAddressInRange('192.168.1.1', '')).toBe(false)
        })

        test('invalid CIDR format', () => {
            expect(isIPAddressInRange('192.168.1.1', '192.168.1.0')).toBe(false)
            expect(isIPAddressInRange('192.168.1.1', '192.168.1.0/')).toBe(false)
            expect(isIPAddressInRange('192.168.1.1', '/24')).toBe(false)
        })

        test('invalid CIDR mask values', () => {
            expect(isIPAddressInRange('192.168.1.1', '192.168.1.0/33')).toBe(false) // IPv4 max is 32
            expect(isIPAddressInRange('2001:db8::1', '2001:db8::/129')).toBe(false) // IPv6 max is 128
            expect(isIPAddressInRange('192.168.1.1', '192.168.1.0/-1')).toBe(false) // Negative
            expect(isIPAddressInRange('192.168.1.1', '192.168.1.0/abc')).toBe(false) // Not a number
        })

        test('invalid IPv4 format', () => {
            expect(isIPAddressInRange('192.168.1', '192.168.1.0/24')).toBe(false) // Missing octet
            expect(isIPAddressInRange('192.168.1.1.5', '192.168.1.0/24')).toBe(false) // Extra octet
            expect(isIPAddressInRange('192.168.1.256', '192.168.1.0/24')).toBe(false) // Octet > 255
            expect(isIPAddressInRange('192.168.1.a', '192.168.1.0/24')).toBe(false) // Non-numeric
        })

        test('invalid IPv6 format', () => {
            expect(isIPAddressInRange('2001:db8', '2001:db8::/32')).toBe(false) // Incomplete
            expect(isIPAddressInRange('2001:db8:::1', '2001:db8::/32')).toBe(false) // Multiple ::
            expect(isIPAddressInRange('2001:db8:gggg::1', '2001:db8::/32')).toBe(false) // Invalid hex
            expect(isIPAddressInRange('2001:db8::1::2', '2001:db8::/32')).toBe(false) // Multiple ::
        })

        test('mixed IP versions', () => {
            expect(isIPAddressInRange('192.168.1.1', '2001:db8::/32')).toBe(false) // IPv4 address, IPv6 prefix
            expect(isIPAddressInRange('2001:db8::1', '192.168.1.0/24')).toBe(false) // IPv6 address, IPv4 prefix
        })

        test('non-string inputs', () => {
            expect(isIPAddressInRange(123 as any, '192.168.1.0/24')).toBe(false)
            expect(isIPAddressInRange('192.168.1.1', 24 as any)).toBe(false)
            expect(isIPAddressInRange({} as any, '192.168.1.0/24')).toBe(false)
            expect(isIPAddressInRange('192.168.1.1', [] as any)).toBe(false)
        })
    })

    // Edge cases
    describe('Edge cases', () => {
        test('handles special IPv4 addresses', () => {
            expect(isIPAddressInRange('127.0.0.1', '127.0.0.0/8')).toBe(true) // Localhost
            expect(isIPAddressInRange('255.255.255.255', '0.0.0.0/0')).toBe(true) // Broadcast
        })

        test('handles special IPv6 addresses', () => {
            expect(isIPAddressInRange('::1', '::1/128')).toBe(true) // Localhost
            expect(isIPAddressInRange('fe80::1', 'fe80::/10')).toBe(true) // Link local
        })
    })
})
