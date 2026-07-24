import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'
import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from 'vitest'

import { serializeQuery } from '../src/core/http'
import {
    createClient,
    MissingApiKeyError,
    PostHogApiError,
    PostHogPermissionError,
    PostHogRateLimitError,
    PostHogValidationError,
} from '../src/index'

interface Captured {
    method: string
    url: string
    auth: string | null
    clientHeader: string | null
    contentType: string | null
    body: string | null
}

const captured: Captured[] = []
const server = setupServer()

async function record(request: Request): Promise<void> {
    captured.push({
        method: request.method,
        url: request.url,
        auth: request.headers.get('authorization'),
        clientHeader: request.headers.get('x-posthog-client'),
        contentType: request.headers.get('content-type'),
        body: request.method === 'GET' ? null : await request.clone().text(),
    })
}

beforeAll(() => server.listen({ onUnhandledRequest: 'error' }))
afterEach(() => {
    server.resetHandlers()
    captured.length = 0
})
afterAll(() => server.close())

const HOST = 'https://app.example.test'

describe('@posthog/sdk core', () => {
    it('sends Bearer auth, X-PostHog-Client, and no body on GET', async () => {
        server.use(
            http.get(`${HOST}/api/projects/42/feature_flags/`, async ({ request }) => {
                await record(request)
                return HttpResponse.json({ results: [] })
            })
        )
        const ph = createClient({ apiKey: 'phx_secret', host: HOST, projectId: 42 })
        await ph.featureFlags.list()
        expect(captured).toHaveLength(1)
        expect(captured[0]!.method).toBe('GET')
        expect(captured[0]!.auth).toBe('Bearer phx_secret')
        expect(captured[0]!.clientHeader).toBe('sdk')
        expect(captured[0]!.body).toBeNull()
    })

    it('trims a trailing slash from host and JSON-encodes request bodies', async () => {
        server.use(
            http.post(`${HOST}/api/projects/42/feature_flags/`, async ({ request }) => {
                await record(request)
                return HttpResponse.json({ id: 1, key: 'beta' })
            })
        )
        const ph = createClient({ apiKey: 'k', host: `${HOST}/`, projectId: 42 })
        const flag = await ph.featureFlags.create({ key: 'beta', name: 'Beta' })
        expect(flag).toEqual({ id: 1, key: 'beta' })
        expect(captured[0]!.contentType).toBe('application/json')
        expect(JSON.parse(captured[0]!.body!)).toMatchObject({ key: 'beta', name: 'Beta' })
    })

    it('threads scalar query params through to the request URL', async () => {
        server.use(
            http.get(`${HOST}/api/projects/42/feature_flags/`, async ({ request }) => {
                await record(request)
                return HttpResponse.json({ results: [] })
            })
        )
        const ph = createClient({ apiKey: 'k', host: HOST, projectId: 42 })
        await ph.featureFlags.list({ search: 'foo', limit: 5 })
        const url = new URL(captured[0]!.url)
        expect(url.searchParams.get('search')).toBe('foo')
        expect(url.searchParams.get('limit')).toBe('5')
    })

    it('serializes scalars directly and JSON-encodes arrays/objects; skips null/empty', () => {
        const qs = serializeQuery({
            search: 'foo',
            limit: 5,
            tags: ['a', 'b'],
            filter: { k: 'v' },
            skipMe: null,
            alsoSkip: undefined,
            emptyArr: [],
        })
        const params = new URLSearchParams(qs)
        expect(params.get('search')).toBe('foo')
        expect(params.get('limit')).toBe('5')
        // Arrays/objects are JSON-encoded so json.loads() backends parse them.
        expect(params.get('tags')).toBe('["a","b"]')
        expect(params.get('filter')).toBe('{"k":"v"}')
        expect(params.has('skipMe')).toBe(false)
        expect(params.has('alsoSkip')).toBe(false)
        expect(params.has('emptyArr')).toBe(false)
    })

    it('preserves the soft-delete semantic (DELETE handler → PATCH { deleted: true })', async () => {
        server.use(
            http.patch(`${HOST}/api/projects/42/feature_flags/7/`, async ({ request }) => {
                await record(request)
                return HttpResponse.json({ id: 7, deleted: true })
            })
        )
        const ph = createClient({ apiKey: 'k', host: HOST, projectId: 42 })
        await ph.featureFlags.delete({ id: 7 })
        expect(captured[0]!.method).toBe('PATCH')
        expect(JSON.parse(captured[0]!.body!)).toEqual({ deleted: true })
    })

    describe('error mapping', () => {
        it('maps 403 permission_denied to PostHogPermissionError with the missing scope', async () => {
            server.use(
                http.get(`${HOST}/api/projects/42/feature_flags/`, () =>
                    HttpResponse.json(
                        {
                            type: 'authentication_error',
                            code: 'permission_denied',
                            detail: "required scope 'feature_flag:read'",
                        },
                        { status: 403 }
                    )
                )
            )
            const ph = createClient({ apiKey: 'k', host: HOST, projectId: 42 })
            await expect(ph.featureFlags.list()).rejects.toMatchObject({
                name: 'PostHogPermissionError',
                missingScope: 'feature_flag:read',
            })
            await expect(ph.featureFlags.list()).rejects.toBeInstanceOf(PostHogPermissionError)
        })

        it('maps validation_error to PostHogValidationError with attr', async () => {
            server.use(
                http.post(`${HOST}/api/projects/42/feature_flags/`, () =>
                    HttpResponse.json(
                        { type: 'validation_error', code: 'invalid', detail: 'key already exists', attr: 'key' },
                        { status: 400 }
                    )
                )
            )
            const ph = createClient({ apiKey: 'k', host: HOST, projectId: 42 })
            await expect(ph.featureFlags.create({ key: 'dup' })).rejects.toMatchObject({
                name: 'PostHogValidationError',
                attr: 'key',
            })
            const err = await ph.featureFlags.create({ key: 'dup' }).catch((e) => e)
            expect(err).toBeInstanceOf(PostHogValidationError)
        })

        it('maps other non-2xx to PostHogApiError carrying the status', async () => {
            server.use(
                http.get(`${HOST}/api/projects/42/feature_flags/`, () =>
                    HttpResponse.json({ detail: 'boom' }, { status: 500 })
                )
            )
            const ph = createClient({ apiKey: 'k', host: HOST, projectId: 42 })
            const err = await ph.featureFlags.list().catch((e) => e)
            expect(err).toBeInstanceOf(PostHogApiError)
            expect(err.status).toBe(500)
        })
    })

    describe('429 retry', () => {
        it('honors Retry-After and retries, then succeeds', async () => {
            let calls = 0
            server.use(
                http.get(`${HOST}/api/projects/42/feature_flags/`, () => {
                    calls++
                    if (calls === 1) {
                        return new HttpResponse('slow down', { status: 429, headers: { 'Retry-After': '0' } })
                    }
                    return HttpResponse.json({ results: [] })
                })
            )
            const ph = createClient({ apiKey: 'k', host: HOST, projectId: 42 })
            await ph.featureFlags.list()
            expect(calls).toBe(2)
        })

        it('throws PostHogRateLimitError after exhausting retries', async () => {
            server.use(
                http.get(
                    `${HOST}/api/projects/42/feature_flags/`,
                    () => new HttpResponse('slow down', { status: 429, headers: { 'Retry-After': '0' } })
                )
            )
            const ph = createClient({ apiKey: 'k', host: HOST, projectId: 42 })
            const err = await ph.featureFlags.list().catch((e) => e)
            expect(err).toBeInstanceOf(PostHogRateLimitError)
            expect(err.retryAfterSeconds).toBe(0)
        })
    })

    describe('configuration & env resolution', () => {
        it('throws MissingApiKeyError (naming the env vars) when no key is available', () => {
            const prev = process.env.POSTHOG_API_KEY
            delete process.env.POSTHOG_API_KEY
            try {
                expect(() => createClient({})).toThrow(MissingApiKeyError)
                expect(() => createClient({})).toThrow(/POSTHOG_API_KEY/)
            } finally {
                if (prev !== undefined) {
                    process.env.POSTHOG_API_KEY = prev
                }
            }
        })

        it('falls back to POSTHOG_API_KEY / POSTHOG_HOST from the environment', async () => {
            vi.stubEnv('POSTHOG_API_KEY', 'phx_env')
            vi.stubEnv('POSTHOG_HOST', HOST)
            try {
                server.use(
                    http.get(`${HOST}/api/projects/9/feature_flags/`, async ({ request }) => {
                        await record(request)
                        return HttpResponse.json({ results: [] })
                    })
                )
                const ph = createClient({ projectId: 9 })
                await ph.featureFlags.list()
                expect(captured[0]!.auth).toBe('Bearer phx_env')
            } finally {
                vi.unstubAllEnvs()
            }
        })
    })

    describe('project scope resolution', () => {
        it('lazily resolves the project id from /api/users/@me/ when unconfigured, once', async () => {
            let meCalls = 0
            server.use(
                http.get(`${HOST}/api/users/@me/`, () => {
                    meCalls++
                    return HttpResponse.json({ team: { id: 123 }, organization: { id: 'org_abc' } })
                }),
                http.get(`${HOST}/api/projects/123/feature_flags/`, async ({ request }) => {
                    await record(request)
                    return HttpResponse.json({ results: [] })
                })
            )
            const ph = createClient({ apiKey: 'k', host: HOST })
            await ph.featureFlags.list()
            await ph.featureFlags.list()
            expect(meCalls).toBe(1) // cached after first resolution
            expect(new URL(captured[0]!.url).pathname).toBe('/api/projects/123/feature_flags/')
        })

        it('honors a per-call projectId override without hitting /@me/', async () => {
            server.use(
                http.get(`${HOST}/api/projects/555/feature_flags/`, async ({ request }) => {
                    await record(request)
                    return HttpResponse.json({ results: [] })
                })
            )
            const ph = createClient({ apiKey: 'k', host: HOST })
            await ph.featureFlags.list({}, { projectId: 555 })
            expect(new URL(captured[0]!.url).pathname).toBe('/api/projects/555/feature_flags/')
        })
    })
})
