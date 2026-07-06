import { readFileSync } from 'node:fs'
import { createServer, type Server } from 'node:http'
import { AddressInfo } from 'node:net'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it } from 'vitest'

import { DirectHttpClient, HttpClient } from './http-client'

/**
 * Real fetch against a real HTTP server — same posture as the agent-shared
 * S3/SeaweedFS tests. No mocking of the transport; the only behaviour
 * worth testing is whether the dispatcher + timeout knobs actually take
 * effect on a real socket.
 */
describe('HttpClient', () => {
    let server: Server
    let baseUrl: string
    let requestCount: number
    let slowResponseGate: ((value: void) => void) | null = null

    beforeAll(async () => {
        server = createServer((req, res) => {
            requestCount += 1
            if (req.url === '/echo') {
                res.setHeader('content-type', 'text/plain')
                res.end('ok')
                return
            }
            if (req.url === '/slow') {
                // Hold the response until the test releases the gate, so we
                // can assert that AbortSignal.timeout actually fires.
                new Promise<void>((resolve) => {
                    slowResponseGate = resolve
                }).then(() => {
                    res.end('eventually')
                })
                return
            }
            res.statusCode = 404
            res.end()
        })
        await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve))
        const addr = server.address() as AddressInfo
        baseUrl = `http://127.0.0.1:${addr.port}`
    })

    afterAll(async () => {
        await new Promise<void>((resolve, reject) => server.close((err) => (err ? reject(err) : resolve())))
    })

    beforeEach(() => {
        requestCount = 0
        slowResponseGate = null
    })

    afterEach(() => {
        // Release any pending slow responses so the server can shut down clean.
        slowResponseGate?.()
    })

    it('makes a direct fetch when no proxyUrl is set', async () => {
        const client = new HttpClient()
        const res = await client.fetch(`${baseUrl}/echo`)
        expect(res.status).toBe(200)
        expect(await res.text()).toBe('ok')
        expect(requestCount).toBe(1)
    })

    it('passes through method + headers + body unchanged', async () => {
        let observed: { method?: string; auth?: string; body?: string } = {}
        const captureServer = createServer((req, res) => {
            let body = ''
            req.on('data', (chunk) => {
                body += chunk
            })
            req.on('end', () => {
                observed = {
                    method: req.method,
                    auth: req.headers['authorization'] as string | undefined,
                    body,
                }
                res.end('done')
            })
        })
        await new Promise<void>((resolve) => captureServer.listen(0, '127.0.0.1', resolve))
        const port = (captureServer.address() as AddressInfo).port

        try {
            const client = new HttpClient()
            const res = await client.fetch(`http://127.0.0.1:${port}/x`, {
                method: 'POST',
                headers: { authorization: 'Bearer tk', 'content-type': 'application/json' },
                body: JSON.stringify({ hello: 'world' }),
            })
            expect(res.status).toBe(200)
            expect(observed.method).toBe('POST')
            expect(observed.auth).toBe('Bearer tk')
            expect(observed.body).toBe('{"hello":"world"}')
        } finally {
            await new Promise<void>((resolve, reject) => captureServer.close((err) => (err ? reject(err) : resolve())))
        }
    })

    it('aborts via the default timeout when caller supplies no signal', async () => {
        const client = new HttpClient({ defaultTimeoutMs: 50 })
        const start = Date.now()
        await expect(client.fetch(`${baseUrl}/slow`)).rejects.toThrow()
        const elapsed = Date.now() - start
        // Timeout fires; the request shouldn't hang waiting for /slow to resolve.
        expect(elapsed).toBeLessThan(1_000)
    })

    it('honours a caller-supplied signal over the default timeout', async () => {
        // Caller passes a long-lived signal; the default timeout should NOT
        // override it. We assert by letting the slow handler resolve quickly
        // and verifying the request completes (instead of being aborted by
        // the 10ms default).
        const client = new HttpClient({ defaultTimeoutMs: 10 })
        const ac = new AbortController()
        const promise = client.fetch(`${baseUrl}/slow`, { signal: ac.signal })
        // Resolve the slow handler after 30ms — past the default timeout.
        setTimeout(() => slowResponseGate?.(), 30)
        const res = await promise
        expect(res.status).toBe(200)
        expect(await res.text()).toBe('eventually')
    })

    it('fails fast when proxyUrl points at an unreachable host', async () => {
        // Build a ProxyAgent against a port nothing's listening on; the
        // outbound fetch should reject rather than silently succeed (i.e.
        // proving the dispatcher is actually wired, not ignored).
        const client = new HttpClient({ proxyUrl: 'http://127.0.0.1:1', defaultTimeoutMs: 1_000 })
        await expect(client.fetch(`${baseUrl}/echo`)).rejects.toThrow()
    })
})

describe('DirectHttpClient', () => {
    let server: Server
    let baseUrl: string

    beforeAll(async () => {
        server = createServer((_req, res) => {
            res.setHeader('content-type', 'text/plain')
            res.end('ok')
        })
        await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve))
        baseUrl = `http://127.0.0.1:${(server.address() as AddressInfo).port}`
    })

    afterAll(async () => {
        await new Promise<void>((resolve, reject) => server.close((err) => (err ? reject(err) : resolve())))
    })

    it('makes a direct fetch with no dispatcher', async () => {
        const client = new DirectHttpClient()
        const res = await client.fetch(`${baseUrl}/echo`)
        expect(res.status).toBe(200)
        expect(await res.text()).toBe('ok')
    })

    it('does NOT accept a proxyUrl in its options — internal-only by construction', () => {
        // Capability check: the class has no constructor knob to wire a
        // proxy. Anyone trying to route author-influenced URLs through
        // here would have to swap to `HttpClient`, which is the seam the
        // proxy guard sits behind. This test is structural — if the
        // option were ever added back, the type signature would change
        // and this assertion would fail to compile.
        const opts: ConstructorParameters<typeof DirectHttpClient>[0] = {}
        // @ts-expect-error proxyUrl is intentionally not part of DirectHttpClient's options
        opts.proxyUrl = 'http://smokescreen:4750'
        expect(opts).toBeTruthy()
    })

    describe('atlas enshrinement double-entry', () => {
        // The coherence atlas may mark a crossing `enshrined: true` (tier-1) only when the
        // illegal value is unrepresentable at compile time. `atlas --check` verifies the
        // marker is backed by a `via guard` claim but CANNOT verify the crossing is genuinely
        // compile-unrepresentable, so a guard-backed-but-runtime crossing would sail through.
        // This is the reconciliation the coherence README mandates: the atlas `enshrined` set
        // must equal the set this suite proves structurally. A name here without a real
        // compile-proof (the @ts-expect-error above) is the over-claim the pairing forbids.
        const STRUCTURALLY_ENSHRINED = ['DirectHttpClient'] // proven by 'does NOT accept a proxyUrl' above

        const configPath = join(dirname(fileURLToPath(import.meta.url)), '../../coherence.config.json')
        const transitions: Record<string, { enshrined?: boolean }> =
            JSON.parse(readFileSync(configPath, 'utf8')).atlas?.transitions ?? {}
        const atlasEnshrined = Object.entries(transitions)
            .filter(([, t]) => t.enshrined === true)
            .map(([sym]) => sym)

        it('every atlas-enshrined crossing has a structural compile-proof in this suite', () => {
            for (const sym of atlasEnshrined) {
                expect(STRUCTURALLY_ENSHRINED).toContain(sym)
            }
        })
        it('every structurally-proven crossing is marked enshrined in the atlas', () => {
            for (const sym of STRUCTURALLY_ENSHRINED) {
                expect(atlasEnshrined).toContain(sym)
            }
        })
    })

    it('default timeout still applies — long-running internal calls do not hang the worker', async () => {
        // Hit a port nothing is listening on so the socket sits open until
        // the abort signal fires. 50ms cap → reject inside 1s.
        const client = new DirectHttpClient({ defaultTimeoutMs: 50 })
        const start = Date.now()
        await expect(client.fetch('http://127.0.0.1:1/never')).rejects.toThrow()
        expect(Date.now() - start).toBeLessThan(1_000)
    })
})
