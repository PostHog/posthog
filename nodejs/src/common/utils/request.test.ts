import dns from 'dns/promises'
import { range } from 'lodash'
import http from 'node:http'
import net, { AddressInfo } from 'node:net'
import { register } from 'prom-client'

import { getExternalRequestConfig } from '~/common/config'

import { parseJSON } from './json-parse'
import {
    FetchOptions,
    SecureRequestError,
    fetch,
    internalFetch,
    legacyFetch,
    raiseIfUserProvidedUrlUnsafe,
} from './request'

const realDnsLookup = jest.requireActual('dns/promises').lookup
jest.mock('dns/promises', () => ({
    lookup: jest.fn((hostname: string, options?: any) => {
        return realDnsLookup(hostname, options)
    }),
}))

// Local HTTP server used in place of flaky external services (httpbin.org, example.com).
// Serves a few httpbin-compatible routes plus a default 200 response.
let testServer: http.Server
let baseUrl: string

beforeAll(async () => {
    testServer = http.createServer((req, res) => {
        const url = new URL(req.url ?? '/', `http://${req.headers.host}`)
        if (url.pathname === '/get') {
            res.writeHead(200, { 'content-type': 'application/json' })
            res.end(JSON.stringify({ url: url.toString() }))
        } else if (url.pathname === '/status/404') {
            res.writeHead(404)
            res.end()
        } else if (url.pathname === '/stream/50') {
            res.writeHead(200, { 'content-type': 'application/json' })
            for (let i = 0; i < 50; i++) {
                res.write(JSON.stringify({ id: i }) + '\n')
            }
            res.end()
        } else {
            res.writeHead(200, { 'content-type': 'text/html' })
            res.end('<html><body>Example</body></html>')
        }
    })
    await new Promise<void>((resolve) => testServer.listen(0, '127.0.0.1', resolve))
    baseUrl = `http://127.0.0.1:${(testServer.address() as AddressInfo).port}`
})

afterAll(async () => {
    // undici keeps connections alive, so force them closed or server.close() never resolves.
    testServer.closeAllConnections()
    await new Promise<void>((resolve, reject) => testServer.close((err) => (err ? reject(err) : resolve())))
})

async function withIsolatedProxy(
    proxy: net.Server,
    run: (fresh: typeof import('./request')) => Promise<void>
): Promise<void> {
    const proxySockets = new Set<net.Socket>()
    proxy.on('connection', (socket: net.Socket) => proxySockets.add(socket))
    await new Promise<void>((resolve) => proxy.listen(0, '127.0.0.1', resolve))
    const overrides: Record<string, string> = {
        NODE_ENV: 'test',
        HTTPS_PROXY: `http://127.0.0.1:${(proxy.address() as AddressInfo).port}`,
        EXTERNAL_REQUEST_CONNECT_TIMEOUT_MS: '200',
    }
    const originalValues = Object.fromEntries(Object.keys(overrides).map((name) => [name, process.env[name]]))
    Object.assign(process.env, overrides)
    try {
        await jest.isolateModulesAsync(async () => {
            // request.ts reads the proxy URL and the timeouts once, at module load.
            const fresh: typeof import('./request') = require('./request')
            try {
                await run(fresh)
            } finally {
                await fresh.closeSharedAgents(100)
            }
        })
    } finally {
        for (const [name, value] of Object.entries(originalValues)) {
            if (value === undefined) {
                delete process.env[name]
            } else {
                process.env[name] = value
            }
        }
        proxySockets.forEach((socket) => socket.destroy())
        proxy.close()
    }
}

function createTunnelingProxy(): http.Server {
    return http.createServer().on('connect', (request: http.IncomingMessage, socket: net.Socket, head: Buffer) => {
        const target = new URL(`http://${request.url}`)
        const upstream = net.connect(Number(target.port), target.hostname, () => {
            socket.write('HTTP/1.1 200 Connection Established\r\n\r\n')
            upstream.write(head)
            upstream.pipe(socket)
            socket.pipe(upstream)
        })
        upstream.on('error', () => socket.destroy())
        socket.on('error', () => upstream.destroy())
    })
}

describe('fetch', () => {
    beforeEach(() => {
        jest.setTimeout(1000)
        jest.mocked(dns.lookup).mockImplementation(realDnsLookup)
        // NOTE: We are testing production-only features hence the override
        process.env.NODE_ENV = 'production'
        delete process.env.DEBUG
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
            // IPv6 literal SSRF bypasses
            ['http://[::ffff:169.254.169.254]/', 'Hostname is not allowed'],
            ['http://[::ffff:127.0.0.1]/', 'Hostname is not allowed'],
            ['http://[::ffff:10.0.0.1]/', 'Hostname is not allowed'],
            ['http://[::ffff:192.168.1.1]/', 'Hostname is not allowed'],
            ['http://[::1]/', 'Hostname is not allowed'],
            ['http://[fe80::1]/', 'Hostname is not allowed'],
            ['http://[fc00::1]/', 'Hostname is not allowed'],
            ['http://[fd12:3456:789a::1]/', 'Hostname is not allowed'],
        ])('should raise against unsafe URLs: %s', async (url, error) => {
            await expect(raiseIfUserProvidedUrlUnsafe(url)).rejects.toThrow(error)
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
            // nosemgrep: typescript.react.security.react-insecure-request.react-insecure-request
            await expect(fetch('http://unknown.domain.unknown')).rejects.toMatchInlineSnapshot(
                `[ResolutionError: Invalid hostname]`
            )
        })

        it('should successfully fetch from safe URLs', async () => {
            // Non-prod so the secure path allows the loopback test server (prod blocks private IPs).
            const originalNodeEnv = process.env.NODE_ENV
            process.env.NODE_ENV = 'test'
            try {
                const response = await fetch(baseUrl)
                expect(response.status).toBe(200)
            } finally {
                process.env.NODE_ENV = originalNodeEnv
            }
        })

        // The split is only worth anything if `fetch` reads the third-party setting and
        // `internalFetch` does not. Wiring either one to the other's budget fails silently: raising
        // the third-party timeout would then do nothing, or internal calls would quietly inherit it.
        it('resolves each entry point against its own timeout setting', async () => {
            const originalNodeEnv = process.env.NODE_ENV
            process.env.NODE_ENV = 'test'
            process.env.EXTERNAL_REQUEST_THIRD_PARTY_TIMEOUT_MS = '7654'
            try {
                await jest.isolateModulesAsync(async () => {
                    // Re-import against the isolated registry: request.ts reads the config once, at
                    // module load, so the override only lands on a fresh copy.
                    const fresh = require('./request')
                    const thirdPartyOptions: FetchOptions = {}
                    const internalOptions: FetchOptions = {}

                    await fresh.fetch(baseUrl, thirdPartyOptions)
                    await fresh.internalFetch(baseUrl, internalOptions)

                    expect(thirdPartyOptions.timeoutMs).toBe(7654)
                    expect(internalOptions.timeoutMs).toBe(getExternalRequestConfig().EXTERNAL_REQUEST_TIMEOUT_MS)
                })
            } finally {
                delete process.env.EXTERNAL_REQUEST_THIRD_PARTY_TIMEOUT_MS
                process.env.NODE_ENV = originalNodeEnv
            }
        }, 10000)

        it.each([
            ['the HTTP/1.1 dispatcher', false],
            ['the HTTP/2 dispatcher', true],
        ])(
            'fails a request through %s at the connect timeout when the proxy never answers the CONNECT',
            async (_dispatcher, allowH2) => {
                await withIsolatedProxy(
                    net.createServer((socket) => socket.on('data', () => undefined)),
                    async (fresh) => {
                        let guard: NodeJS.Timeout | undefined
                        const outcome = await Promise.race([
                            fresh
                                .fetchStreamed('https://images.example.com/a.png', { timeoutMs: 30_000, allowH2 })
                                .then(
                                    () => 'resolved',
                                    (error: { code?: string }) => error.code
                                ),
                            new Promise((resolve) => {
                                guard = setTimeout(() => resolve('still pending'), 3000)
                            }),
                        ])
                        clearTimeout(guard)

                        expect(outcome).toBe('UND_ERR_HEADERS_TIMEOUT')
                    }
                )
            },
            10000
        )

        it.each([
            ['the HTTP/1.1 dispatcher', false],
            ['the HTTP/2 dispatcher', true],
        ])(
            'keeps the request timeout through %s for a response that comes after the connect timeout',
            async (_dispatcher, allowH2) => {
                const slowOrigin = http.createServer((_request, response) => {
                    setTimeout(() => {
                        response.writeHead(200, { 'content-type': 'image/png' })
                        response.end('image')
                    }, 1500)
                })
                await new Promise<void>((resolve) => slowOrigin.listen(0, '127.0.0.1', resolve))
                const originPort = (slowOrigin.address() as AddressInfo).port
                try {
                    await withIsolatedProxy(createTunnelingProxy(), async (fresh) => {
                        const response = await fresh.fetchStreamed(`http://127.0.0.1:${originPort}/a.png`, {
                            timeoutMs: 5000,
                            allowH2,
                        })
                        const { bytes } = await response.read(1024)

                        expect(response.status).toBe(200)
                        expect(bytes.toString()).toBe('image')
                    })
                } finally {
                    slowOrigin.closeAllConnections()
                    slowOrigin.close()
                }
            },
            10000
        )

        it('keeps a timeout the caller set explicitly', async () => {
            const originalNodeEnv = process.env.NODE_ENV
            process.env.NODE_ENV = 'test'
            try {
                const options: FetchOptions = { timeoutMs: 1234 }
                await fetch(baseUrl, options)
                expect(options.timeoutMs).toBe(1234)
            } finally {
                process.env.NODE_ENV = originalNodeEnv
            }
        })

        it.each([
            ['http://[::ffff:169.254.169.254]/latest/api/token', 'IPv6-mapped IMDS'],
            ['http://[::ffff:127.0.0.1]/', 'IPv6-mapped loopback'],
            ['http://[::ffff:10.0.0.1]/', 'IPv6-mapped private'],
            ['http://[::ffff:192.168.1.1]/', 'IPv6-mapped private'],
            ['http://[::1]/', 'IPv6 loopback'],
            ['http://[fe80::1]/', 'IPv6 link-local'],
            ['http://[fc00::1]/', 'IPv6 unique-local'],
            ['http://[fd12:3456:789a::1]/', 'IPv6 unique-local'],
            ['http://169.254.169.254/latest/api/token', 'IPv4 IMDS'],
            ['http://127.0.0.1/', 'IPv4 loopback'],
        ])('should block IP literal SSRF bypasses: %s (%s)', async (url) => {
            await expect(fetch(url)).rejects.toThrow(new SecureRequestError('Hostname is not allowed'))
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

            // nosemgrep: typescript.react.security.react-insecure-request.react-insecure-request
            await expect(fetch(`http://example.com`)).rejects.toThrow(new SecureRequestError(`Hostname is not allowed`))
        })

        it('uses secure DNS lookup when HTTP/2 is enabled', async () => {
            jest.mocked(dns.lookup).mockResolvedValue([{ address: '10.0.0.1', family: 4 }] as any)

            await expect(fetch('https://example.com', { allowH2: true })).rejects.toThrow(
                new SecureRequestError('Hostname is not allowed')
            )
        })

        it.each([
            ['::ffff:169.254.169.254', 'IPv6-mapped IMDS'],
            ['::ffff:127.0.0.1', 'IPv6-mapped loopback'],
            ['::ffff:10.0.0.1', 'IPv6-mapped private'],
            ['::ffff:192.168.1.1', 'IPv6-mapped private'],
            ['::ffff:0.0.0.0', 'IPv6-mapped this network'],
        ])('should block IPv6-mapped IPv4 addresses: %s (%s)', async (ip) => {
            jest.mocked(dns.lookup).mockResolvedValue([{ address: ip, family: 6 }] as any)

            // nosemgrep: typescript.react.security.react-insecure-request.react-insecure-request
            await expect(fetch(`http://example.com`)).rejects.toThrow(new SecureRequestError(`Hostname is not allowed`))
        })

        it.each([
            ['::1', 'IPv6 loopback'],
            ['fe80::1', 'IPv6 link-local'],
            ['fc00::1', 'IPv6 unique-local'],
            ['fd12:3456:789a::1', 'IPv6 unique-local'],
        ])('should block non-global pure IPv6 addresses: %s (%s)', async (ip) => {
            jest.mocked(dns.lookup).mockResolvedValue([{ address: ip, family: 6 }] as any)

            // nosemgrep: typescript.react.security.react-insecure-request.react-insecure-request
            await expect(fetch(`http://example.com`)).rejects.toThrow(new SecureRequestError(`Hostname is not allowed`))
        })

        it('should allow globally routable IPv6 addresses', async () => {
            jest.mocked(dns.lookup).mockResolvedValue([{ address: '2607:f8b0:4004:800::200e', family: 6 }] as any)

            // This will fail to connect since it's a mock DNS result, but it should NOT throw SecureRequestError
            await expect(fetch(`http://example.com`)).rejects.not.toThrow(SecureRequestError) // nosemgrep: typescript.react.security.react-insecure-request.react-insecure-request
        })

        // A gauge that is incremented but not decremented drifts up forever, and nothing else reads this one, so a
        // leak on either path would go unnoticed until it had already made the metric useless.
        it.each([
            [
                'a lookup that resolves',
                () => jest.mocked(dns.lookup).mockResolvedValue([{ address: '10.0.0.1', family: 4 }] as any),
            ],
            ['a lookup that rejects', () => jest.mocked(dns.lookup).mockRejectedValue(new Error('ENOTFOUND'))],
        ])('releases the in-flight DNS gauge after %s', async (_name, applyMock) => {
            const readGauge = async (): Promise<number> =>
                (await register.getSingleMetric('node_dns_lookups_in_flight')!.get()).values[0].value

            applyMock()
            const before = await readGauge()

            // nosemgrep: typescript.react.security.react-insecure-request.react-insecure-request
            await expect(fetch(`http://example.com`)).rejects.toThrow()

            expect(dns.lookup).toHaveBeenCalled()
            expect(await readGauge()).toEqual(before)
        })
    })

    describe('parallel requests execution', () => {
        jest.retryTimes(3, { logErrorsBeforeRetry: true })
        // NOTE: This is inherently flakey so we disable it except when validating changes for it
        it.skip('should execute requests in parallel - completion time test', async () => {
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

type IsolatedRequest = {
    request: typeof import('./request')
    lookup: jest.Mock
    readNegativeCacheCounter: (result: string) => Promise<number>
}

// request.ts reads the DNS settings once, at module load, so each case loads a fresh copy with its own environment.
async function withDnsConfig(env: Record<string, string>, run: (isolated: IsolatedRequest) => Promise<void>) {
    const originalValues = Object.fromEntries(Object.keys(env).map((name) => [name, process.env[name]]))
    Object.assign(process.env, env)
    try {
        await jest.isolateModulesAsync(async () => {
            const request: typeof import('./request') = require('./request')
            const lookup = jest.mocked(require('dns/promises').lookup)
            const registry: typeof register = require('prom-client').register
            const readNegativeCacheCounter = async (result: string): Promise<number> =>
                (await registry.getSingleMetric('node_dns_negative_cache_total')!.get()).values.find(
                    (value) => value.labels.result === result
                )?.value ?? 0
            try {
                await run({ request, lookup, readNegativeCacheCounter })
            } finally {
                await request.closeSharedAgents(100)
            }
        })
    } finally {
        for (const [name, value] of Object.entries(originalValues)) {
            if (value === undefined) {
                delete process.env[name]
            } else {
                process.env[name] = value
            }
        }
    }
}

const dnsError = (code: string): Error => Object.assign(new Error(`getaddrinfo ${code} example.com`), { code })

describe('DNS lookup settings', () => {
    it('resolves hostnames as absolute names when absolute lookups are enabled', async () => {
        await withDnsConfig({ EXTERNAL_REQUEST_DNS_ABSOLUTE_LOOKUP: 'true' }, async ({ request, lookup }) => {
            lookup.mockResolvedValue([{ address: '1.1.1.1', family: 4 }])

            await request.raiseIfUserProvidedUrlUnsafe('https://example.com/path')
            await request.raiseIfUserProvidedUrlUnsafe('https://already-absolute.com./path')

            expect(lookup.mock.calls.map(([hostname]) => hostname)).toEqual(['example.com.', 'already-absolute.com.'])
        })
    })

    it('resolves hostnames as given when absolute lookups are disabled', async () => {
        await withDnsConfig({ EXTERNAL_REQUEST_DNS_ABSOLUTE_LOOKUP: 'false' }, async ({ request, lookup }) => {
            lookup.mockResolvedValue([{ address: '1.1.1.1', family: 4 }])

            await request.raiseIfUserProvidedUrlUnsafe('https://example.com/path')

            expect(lookup).toHaveBeenCalledWith('example.com', { all: true })
        })
    })

    it('skips the lookup for a hostname that recently returned ENOTFOUND in enforce mode', async () => {
        await withDnsConfig(
            { EXTERNAL_REQUEST_DNS_NEGATIVE_CACHE_MODE: 'enforce' },
            async ({ request, lookup, readNegativeCacheCounter }) => {
                lookup.mockRejectedValue(dnsError('ENOTFOUND'))

                await expect(request.raiseIfUserProvidedUrlUnsafe('https://example.com')).rejects.toThrow(
                    'Invalid hostname'
                )
                await expect(request.raiseIfUserProvidedUrlUnsafe('https://example.com')).rejects.toThrow(
                    'Invalid hostname'
                )

                expect(lookup).toHaveBeenCalledTimes(1)
                expect(await readNegativeCacheCounter('hit')).toEqual(1)
            }
        )
    })

    // A timeout can come from an overloaded resolver rather than from the hostname. Caching it would fail healthy
    // destinations for as long as the resolver stays slow.
    it.each(['EAI_AGAIN', 'ETIMEOUT'])('does not cache a %s failure', async (code) => {
        await withDnsConfig({ EXTERNAL_REQUEST_DNS_NEGATIVE_CACHE_MODE: 'enforce' }, async ({ request, lookup }) => {
            lookup.mockRejectedValue(dnsError(code))

            await expect(request.raiseIfUserProvidedUrlUnsafe('https://example.com')).rejects.toThrow()
            await expect(request.raiseIfUserProvidedUrlUnsafe('https://example.com')).rejects.toThrow()

            expect(lookup).toHaveBeenCalledTimes(2)
        })
    })

    it('still looks up a cached hostname in shadow mode and counts what enforce mode would skip', async () => {
        await withDnsConfig(
            { EXTERNAL_REQUEST_DNS_NEGATIVE_CACHE_MODE: 'shadow' },
            async ({ request, lookup, readNegativeCacheCounter }) => {
                lookup.mockRejectedValueOnce(dnsError('ENOTFOUND'))
                lookup.mockRejectedValueOnce(dnsError('ENOTFOUND'))
                lookup.mockResolvedValueOnce([{ address: '1.1.1.1', family: 4 }])

                await expect(request.raiseIfUserProvidedUrlUnsafe('https://example.com')).rejects.toThrow()
                await expect(request.raiseIfUserProvidedUrlUnsafe('https://example.com')).rejects.toThrow()
                await request.raiseIfUserProvidedUrlUnsafe('https://example.com')

                expect(lookup).toHaveBeenCalledTimes(3)
                expect(await readNegativeCacheCounter('shadow_hit')).toEqual(2)
                expect(await readNegativeCacheCounter('shadow_hit_resolved')).toEqual(1)
            }
        )
    })

    it('rejects an unknown negative cache mode at startup', async () => {
        await expect(
            withDnsConfig({ EXTERNAL_REQUEST_DNS_NEGATIVE_CACHE_MODE: 'on' }, () => Promise.resolve())
        ).rejects.toThrow('EXTERNAL_REQUEST_DNS_NEGATIVE_CACHE_MODE must be one of off, shadow, enforce')
    })
})

describe('legacyFetch', () => {
    beforeEach(() => {
        jest.setTimeout(1000)
        jest.mocked(dns.lookup).mockImplementation(realDnsLookup)
        // NOTE: We are testing production-only features hence the override
        process.env.NODE_ENV = 'production'
        delete process.env.DEBUG
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
            // Non-prod so the secure path allows the loopback test server (prod blocks private IPs).
            const originalNodeEnv = process.env.NODE_ENV
            process.env.NODE_ENV = 'test'
            try {
                const response = await legacyFetch(baseUrl)
                expect(response.ok).toBe(true)
            } finally {
                process.env.NODE_ENV = originalNodeEnv
            }
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
        jest.retryTimes(3, { logErrorsBeforeRetry: true })
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

describe('_fetch response body handling', () => {
    // Use internalFetch to skip SSRF DNS checks which fail in CI, hitting the shared
    // local server (see top of file) to avoid flaky external services.
    it('should return response body via text()', async () => {
        const response = await internalFetch(baseUrl)
        const text = await response.text()
        expect(typeof text).toBe('string')
        expect(text.length).toBeGreaterThan(0)
        expect(response.status).toBe(200)
    })

    it('should parse response via json() when valid JSON', async () => {
        const response = await internalFetch(`${baseUrl}/get`)
        const json = await response.json()
        expect(json).toHaveProperty('url')
    })

    it('should return the same result on multiple text() calls', async () => {
        const response = await internalFetch(baseUrl)
        const first = await response.text()
        const second = await response.text()
        expect(first).toBe(second)
        expect(first.length).toBeGreaterThan(0)
    })

    it('should return the same result for concurrent text() calls', async () => {
        const response = await internalFetch(baseUrl)
        const [a, b] = await Promise.all([response.text(), response.text()])
        expect(a).toBe(b)
        expect(a.length).toBeGreaterThan(0)
    })

    it('should return empty string after dump() is called', async () => {
        const response = await internalFetch(baseUrl)
        await response.dump()
        expect(await response.text()).toBe('')
    })

    it('should return correct status code for error responses', async () => {
        const response = await internalFetch(`${baseUrl}/status/404`)
        expect(response.status).toBe(404)
    })

    it('should parse headers', async () => {
        const response = await internalFetch(baseUrl)
        expect(response.headers['content-type']).toBeDefined()
    })

    it('should fully read streamed/chunked response bodies', async () => {
        const response = await internalFetch(`${baseUrl}/stream/50`)
        const text = await response.text()
        const lines = text.trim().split('\n')
        expect(lines.length).toBe(50)
        for (const line of lines) {
            expect(() => parseJSON(line)).not.toThrow()
        }
    })
})
