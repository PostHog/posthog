import { FetchError } from 'node-fetch'

import { legacyFetch } from './fetch'

// Restore the real fetch implementation for this test file
jest.unmock('node-fetch')

const realDnsLookup = jest.requireActual('dns/promises').lookup
jest.mock('dns/promises', () => ({
    lookup: jest.fn((hostname: string, options?: any) => {
        return realDnsLookup(hostname, options)
    }),
}))

import dns from 'dns/promises'
import { range } from 'lodash'

describe('legacyFetch', () => {
    beforeEach(() => {
        jest.setTimeout(1000)
        jest.mocked(dns.lookup).mockImplementation(realDnsLookup)
        // NOTE: We are testing production-only features hence the override
        process.env.NODE_ENV = 'production'
    })

    describe('calls', () => {
        // By default security features are only enabled in production but for tests we want to enable them
        it('should raise if the URL is unsafe', async () => {
            await expect(legacyFetch('http://localhost')).rejects.toMatchInlineSnapshot(
                `[FetchError: request to http://localhost/ failed, reason: Internal hostname]`
            )
        })

        it('should raise if the URL is unknown', async () => {
            await expect(legacyFetch('http://unknown.domain.unknown')).rejects.toMatchInlineSnapshot(
                `[FetchError: request to http://unknown.domain.unknown/ failed, reason: Invalid hostname]`
            )
        })

        it('should successfully fetch from safe URLs', async () => {
            // This will make a real HTTP request
            const response = await legacyFetch('https://example.com')
            expect(response.ok).toBe(true)
        })
    })

    describe('IPv4 address validation', () => {
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

            await expect(legacyFetch(`http://example.com`)).rejects.toThrow(
                new FetchError(`request to http://example.com/ failed, reason: Internal hostname`, 'posthog-host-guard')
            )
        })
    })

    // NOTE: Skipped as this is mostly to validate against the new request implementation
    describe.skip('parallel requests execution', () => {
        jest.retryTimes(3)
        it('should execute requests in parallel', async () => {
            const start = performance.now()
            const timings: number[] = []
            const parallelRequests = 100

            const requests = range(parallelRequests).map(() =>
                legacyFetch('https://example.com').then(() => {
                    timings.push(performance.now() - start)
                })
            )

            await Promise.all(requests)

            expect(timings).toHaveLength(parallelRequests)

            // NOTE: Not the easiest thing to test - what we are testing is that the requests are executed in parallel
            // so the total time should be close to the time it takes to execute one request.
            // It's far from perfect but it at the very least caches
            const totalTime = performance.now() - start
            const firstTime = timings[0]

            expect(totalTime).toBeGreaterThan(firstTime - 100)
            expect(totalTime).toBeLessThan(firstTime + 100)
        })
    })
})
