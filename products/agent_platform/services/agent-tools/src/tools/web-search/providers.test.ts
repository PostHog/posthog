import { describe, expect, it } from 'vitest'

import type { HttpFetcher, WebSearchInput } from '@posthog/agent-shared'

import { BraveProvider, ExaProvider, TavilyProvider } from './providers'

/** Build an HttpFetcher that records the request and returns a JSON response. */
function jsonFetch(
    body: unknown,
    opts?: { status?: number }
): {
    http: HttpFetcher
    call: { url?: string; init?: RequestInit }
} {
    const call: { url?: string; init?: RequestInit } = {}
    const status = opts?.status ?? 200
    const http: HttpFetcher = {
        fetch: async (input, init) => {
            call.url = typeof input === 'string' ? input : input.toString()
            call.init = init
            return {
                ok: status >= 200 && status < 300,
                status,
                json: async () => body,
            } as unknown as Response
        },
    }
    return { http, call }
}

const INPUT: WebSearchInput = { query: 'posthog feature flags', limit: 3 }

describe('web-search providers', () => {
    describe('ExaProvider', () => {
        it('POSTs to api.exa.ai with the api key header and maps highlights to snippet', async () => {
            const { http, call } = jsonFetch({
                results: [
                    { title: 'A', url: 'https://a', highlights: ['one', 'two'] },
                    { title: 'B', url: 'https://b', text: 'fallback text' },
                ],
            })
            const out = await new ExaProvider('exa-key').search(INPUT, http)
            expect(call.url).toBe('https://api.exa.ai/search')
            expect(call.init?.method).toBe('POST')
            const headers = call.init?.headers as Record<string, string>
            expect(headers['x-api-key']).toBe('exa-key')
            expect(JSON.parse(call.init?.body as string)).toEqual({
                query: INPUT.query,
                numResults: 3,
                contents: { highlights: true },
            })
            expect(out).toEqual([
                { title: 'A', url: 'https://a', snippet: 'one … two' },
                { title: 'B', url: 'https://b', snippet: 'fallback text' },
            ])
        })

        it('throws exa_http_<status> on a non-2xx response', async () => {
            const { http } = jsonFetch({}, { status: 500 })
            await expect(new ExaProvider('k').search(INPUT, http)).rejects.toThrow(/exa_http_500/)
        })

        it('tolerates a missing results array', async () => {
            const { http } = jsonFetch({})
            expect(await new ExaProvider('k').search(INPUT, http)).toEqual([])
        })
    })

    describe('TavilyProvider', () => {
        it('POSTs to api.tavily.com with a bearer token and maps content to snippet', async () => {
            const { http, call } = jsonFetch({
                results: [{ title: 'T', url: 'https://t', content: 'desc' }],
            })
            const out = await new TavilyProvider('tav-key').search(INPUT, http)
            expect(call.url).toBe('https://api.tavily.com/search')
            const headers = call.init?.headers as Record<string, string>
            expect(headers.authorization).toBe('Bearer tav-key')
            expect(JSON.parse(call.init?.body as string)).toEqual({
                query: INPUT.query,
                max_results: 3,
                search_depth: 'basic',
            })
            expect(out).toEqual([{ title: 'T', url: 'https://t', snippet: 'desc' }])
        })

        it('throws tavily_http_<status> on a non-2xx response', async () => {
            const { http } = jsonFetch({}, { status: 401 })
            await expect(new TavilyProvider('k').search(INPUT, http)).rejects.toThrow(/tavily_http_401/)
        })
    })

    describe('BraveProvider', () => {
        it('GETs api.search.brave.com with the subscription token and maps description to snippet', async () => {
            const { http, call } = jsonFetch({
                web: { results: [{ title: 'Br', url: 'https://br', description: 'd' }] },
            })
            const out = await new BraveProvider('brave-key').search(INPUT, http)
            expect(call.url).toBe('https://api.search.brave.com/res/v1/web/search?q=posthog+feature+flags&count=3')
            expect(call.init?.method).toBe('GET')
            const headers = call.init?.headers as Record<string, string>
            expect(headers['x-subscription-token']).toBe('brave-key')
            expect(out).toEqual([{ title: 'Br', url: 'https://br', snippet: 'd' }])
        })

        it('throws brave_http_<status> on a non-2xx response', async () => {
            const { http } = jsonFetch({}, { status: 429 })
            await expect(new BraveProvider('k').search(INPUT, http)).rejects.toThrow(/brave_http_429/)
        })
    })

    it('clips snippets longer than the cap', async () => {
        const long = 'x'.repeat(5_000)
        const { http } = jsonFetch({ results: [{ title: 'A', url: 'https://a', text: long }] })
        const out = await new ExaProvider('k').search(INPUT, http)
        expect(out[0].snippet.length).toBe(2_000)
    })

    it('falls back to text when highlights are all empty rather than emitting bare ellipses', async () => {
        const { http } = jsonFetch({
            results: [{ title: 'A', url: 'https://a', highlights: ['', ''], text: 'actual text' }],
        })
        const out = await new ExaProvider('k').search(INPUT, http)
        expect(out[0].snippet).toBe('actual text')
    })

    it('treats a JSON null response body as an empty result set rather than throwing a TypeError', async () => {
        expect(await new ExaProvider('k').search(INPUT, jsonFetch(null).http)).toEqual([])
        expect(await new TavilyProvider('k').search(INPUT, jsonFetch(null).http)).toEqual([])
        expect(await new BraveProvider('k').search(INPUT, jsonFetch(null).http)).toEqual([])
    })

    it('does not expose the API key on enumerable instance properties', () => {
        const provider = new ExaProvider('secret-key')
        expect(JSON.stringify(provider)).not.toContain('secret-key')
        expect(JSON.stringify(provider)).toBe('{"name":"exa"}')
    })
})
