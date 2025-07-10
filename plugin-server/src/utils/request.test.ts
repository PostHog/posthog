const realDnsLookup = jest.requireActual('dns/promises').lookup
jest.mock('dns/promises', () => ({
    lookup: jest.fn((hostname: string, options?: any) => {
        return realDnsLookup(hostname, options)
    }),
}))

import dns from 'dns/promises'
import { range } from 'lodash'

import { fetch, legacyFetch, raiseIfUserProvidedUrlUnsafe, SecureRequestError } from './request'

describe('fetch', () => {
    beforeEach(() => {
        jest.setTimeout(1000)
        jest.mocked(dns.lookup).mockImplementation(realDnsLookup)
        // NOTE: We are testing production-only features hence the override
        process.env.NODE_ENV = 'production'
    })
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
            ['http://localhost', 'Hostname is not allowed'],
            ['http://192.168.0.5', 'Hostname is not allowed'],
            ['http://0.0.0.0', 'Hostname is not allowed'],
            ['http://10.0.0.24', 'Hostname is not allowed'],
            ['http://172.20.0.21', 'Hostname is not allowed'],
            ['http://fgtggggzzggggfd.com', 'Invalid hostname'],
        ])('should raise against unsafe URLs: %s', async (url, error) => {
            await expect(raiseIfUserProvidedUrlUnsafe(url)).rejects.toThrow(new SecureRequestError(error))
        })
    })

    describe('fetch call', () => {
        // By default security features are only enabled in production but for tests we want to enable them

        it('should raise if the URL is unsafe', async () => {
            await expect(fetch('http://localhost')).rejects.toMatchInlineSnapshot(
                `[SecureRequestError: Hostname is not allowed]`
            )
        })

        it('should raise if the URL is unknown', async () => {
            await expect(fetch('http://unknown.domain.unknown')).rejects.toMatchInlineSnapshot(
                `[ResolutionError: Invalid hostname]`
            )
        })

        it('should successfully fetch from safe URLs', async () => {
            // This will make a real HTTP request
            const response = await fetch('https://example.com')
            expect(response.status).toBe(200)
        })
    })

    describe('Address validation', () => {
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

            await expect(fetch(`http://example.com`)).rejects.toThrow(new SecureRequestError(`Hostname is not allowed`))
        })
    })

    describe('parallel requests execution', () => {
        jest.retryTimes(3)
        it('should execute requests in parallel - completion time test', async () => {
            const delayMs = 200
            const parallelRequests = 20

            // Measure sequential execution
            const sequentialStart = performance.now()
            for (let i = 0; i < parallelRequests; i++) {
                await fetch(`https://httpbin.org/delay/${delayMs / 1000}`)
            }
            const sequentialTime = performance.now() - sequentialStart

            const parallelStart = performance.now()
            await Promise.all(range(parallelRequests).map(() => fetch(`https://httpbin.org/delay/${delayMs / 1000}`)))
            const parallelTime = performance.now() - parallelStart

            // Parallel should be significantly faster than sequential
            const speedup = sequentialTime / parallelTime
            expect(speedup).toBeGreaterThan(3)
        })
    })
})

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
            await expect(legacyFetch('http://localhost')).rejects.toMatchInlineSnapshot(`[TypeError: fetch failed]`)
        })

        it('should raise if the URL is unknown', async () => {
            await expect(legacyFetch('http://unknown.domain.unknown')).rejects.toMatchInlineSnapshot(
                `[TypeError: fetch failed]`
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

            const err = await legacyFetch(`http://example.com`).catch((err) => {
                return err
            })

            expect(err.name).toBe('TypeError')
            expect(err.toString()).toContain('fetch failed')
            expect(err.cause.toString()).toContain('Hostname is not allowed')
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
