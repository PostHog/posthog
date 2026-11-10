import { createHmac } from 'crypto'
import { IncomingMessage } from 'http'

import { GeoIp } from '~/common/utils/geoip'

import { createRegionBlockCheck } from './region-block'

describe('createRegionBlockCheck', () => {
    const countries: Record<string, string> = {
        '5.255.255.1': 'RU',
        '8.8.8.8': 'US',
        '2a02:6b8::1': 'RU',
    }
    const geoip: GeoIp = {
        city: (ip) => (countries[ip] ? ({ country: { isoCode: countries[ip] } } as any) : null),
    }
    const request = (forwardedFor: string | undefined, remoteAddress = '10.0.0.1'): IncomingMessage =>
        ({
            headers: forwardedFor === undefined ? {} : { 'x-forwarded-for': forwardedFor },
            socket: { remoteAddress },
        }) as any

    it.each([
        ['the client in X-Forwarded-For is in a blocked country', request('5.255.255.1, 10.0.0.2'), true],
        ['only a proxy hop is in a blocked country', request('8.8.8.8, 5.255.255.1'), false],
        ['the client sends a port with an IPv4 address', request('5.255.255.1:443'), true],
        ['the client sends a bracketed IPv6 address with a port', request('[2a02:6b8::1]:443'), true],
        ['the address is not an IP', request('not-an-ip'), true],
        ['GeoIP cannot place the address', request('203.0.113.9'), false],
        ['there is no X-Forwarded-For and the socket is in a blocked country', request(undefined, '5.255.255.1'), true],
    ])('when %s, blocked is %s', (_name, req, expected) => {
        expect(createRegionBlockCheck(['RU', 'BY'], geoip)(req)).toBe(expected)
    })

    const signed = (ip: string, key: string, ageSeconds = 0): IncomingMessage => {
        const timestamp = String(Math.floor(Date.now() / 1000 - ageSeconds))
        return {
            headers: {
                'x-forwarded-for': '8.8.8.8',
                'x-posthog-client-ip': ip,
                'x-posthog-client-ip-timestamp': timestamp,
                'x-posthog-client-ip-signature': createHmac('sha256', key).update(`${ip}:${timestamp}`).digest('hex'),
            },
            socket: { remoteAddress: '10.0.0.1' },
        } as any
    }

    it.each([
        ['a valid signature uses the signed client IP', signed('5.255.255.1', 'key-b'), true],
        ['a signature from an unknown key falls back to the edge IP', signed('5.255.255.1', 'other'), false],
        ['an expired signature falls back to the edge IP', signed('5.255.255.1', 'key-a', 120), false],
    ])('managed proxy: %s', (_name, req, expected) => {
        expect(createRegionBlockCheck(['RU'], geoip, ['key-a', 'key-b'])(req)).toBe(expected)
    })

    it('blocks nothing when no regions are configured', () => {
        expect(createRegionBlockCheck([], geoip)(request('5.255.255.1'))).toBe(false)
    })
})
