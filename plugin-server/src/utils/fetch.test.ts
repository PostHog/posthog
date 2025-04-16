import { FetchError } from 'node-fetch'

import { raiseIfUserProvidedUrlUnsafe, SecureFetch } from './fetch'

// Restore the real fetch implementation for this test file
jest.unmock('node-fetch')

const realDnsLookup = jest.requireActual('dns/promises').lookup
jest.mock('dns/promises', () => ({
    lookup: jest.fn((hostname: string, options?: any) => {
        return realDnsLookup(hostname, options)
    }),
}))

import dns from 'dns/promises'

describe('secureFetch', () => {
    jest.setTimeout(1000)
    describe('raiseIfUserProvidedUrlUnsafe', () => {
        it.each([
            'https://google.com?q=20', // Safe
            'https://posthog.com', // Safe
            'https://posthog.com/foo/bar', // Safe, with path
            'https://posthog.com:443', // Safe, good port
            'https://1.1.1.1', // Safe, public IP
        ])('should allow safe URLs: %s', async (url) => {
            await expect(raiseIfUserProvidedUrlUnsafe(url)).resolves.not.toThrow()
        })

        it.each([
            ['', 'Invalid URL'],
            ['@@@', 'Invalid URL'],
            ['posthog.com', 'Invalid URL'],
            ['ftp://posthog.com', 'Scheme must be either HTTP or HTTPS'],
            ['http://localhost', 'Internal hostname'],
            ['http://192.168.0.5', 'Internal hostname'],
            ['http://0.0.0.0', 'Internal hostname'],
            ['http://10.0.0.24', 'Internal hostname'],
            ['http://172.20.0.21', 'Internal hostname'],
            ['http://fgtggggzzggggfd.com', 'Invalid hostname'],
        ])('should raise against unsafe URLs: %s', async (url, error) => {
            await expect(raiseIfUserProvidedUrlUnsafe(url)).rejects.toThrow(new FetchError(error, 'posthog-host-guard'))
        })
    })

    describe('trackedFetch', () => {
        // By default security features are only enabled in production but for tests we want to enable them
        const trackedFetch = new SecureFetch({
            allowUnsafe: false,
        })

        it('should raise if the URL is unsafe', async () => {
            await expect(trackedFetch.fetch('http://localhost')).rejects.toMatchInlineSnapshot(
                `[FetchError: request to http://localhost/ failed, reason: Internal hostname]`
            )
        })

        it('should raise if the URL is unknown', async () => {
            await expect(trackedFetch.fetch('http://unknown.domain.unknown')).rejects.toMatchInlineSnapshot(
                `[FetchError: request to http://unknown.domain.unknown/ failed, reason: Invalid hostname]`
            )
        })

        it('should successfully fetch from safe URLs', async () => {
            // This will make a real HTTP request
            const response = await trackedFetch.fetch('https://example.com')
            expect(response.ok).toBe(true)
        })
    })

    describe('IPv4 address validation', () => {
        const trackedFetch = new SecureFetch({
            allowUnsafe: false,
        })

        beforeEach(() => {
            jest.mocked(dns.lookup).mockClear()
        })

        it.each([
            ['0.0.0.0', 'This network'],
            ['0.1.2.3', 'This network'],
            ['127.0.0.1', 'Loopback'],
            ['127.1.2.3', 'Loopback'],
            ['169.254.0.1', 'Link-local'],
            ['169.254.1.2', 'Link-local'],
            ['255.255.255.255', 'Broadcast'],
            ['224.0.0.1', 'Non-unicast (multicast)'],
            ['192.168.1.1', 'Private network'],
            ['10.0.0.1', 'Private network'],
            ['172.16.0.1', 'Private network'],
        ])('should block requests to %s (%s)', async (ip) => {
            jest.mocked(dns.lookup).mockResolvedValue([{ address: ip, family: 4 }] as any)

            await expect(trackedFetch.fetch(`http://example.com`)).rejects.toThrow(
                new FetchError(`request to http://example.com/ failed, reason: Internal hostname`, 'posthog-host-guard')
            )
        })
    })
})
