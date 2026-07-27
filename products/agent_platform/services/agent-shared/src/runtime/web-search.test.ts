import { describe, expect, it, vi } from 'vitest'

import type { HttpFetcher } from './http-client'
import { searchWithFallback, type WebSearchProvider, type WebSearchResult } from './web-search'

const noopHttp = { fetch: vi.fn() } as unknown as HttpFetcher
const noopLog = vi.fn()

function provider(name: WebSearchProvider['name'], impl: () => Promise<WebSearchResult[]>): WebSearchProvider {
    return { name, search: impl }
}

const HIT: WebSearchResult = { title: 't', url: 'https://x', snippet: 's' }

describe('searchWithFallback', () => {
    it('throws web_search_not_configured when the chain is empty', async () => {
        await expect(searchWithFallback([], { query: 'q', limit: 5 }, noopHttp, noopLog)).rejects.toThrow(
            /web_search_not_configured/
        )
    })

    it('returns the first provider on success and does not call later providers', async () => {
        const second = vi.fn(async () => [HIT])
        const out = await searchWithFallback(
            [provider('exa', async () => [HIT]), provider('tavily', second)],
            { query: 'q', limit: 5 },
            noopHttp,
            noopLog
        )
        expect(out.provider).toBe('exa')
        expect(out.results).toEqual([HIT])
        expect(second).not.toHaveBeenCalled()
    })

    it('falls through to the next provider when one throws, logging the failure', async () => {
        const log = vi.fn()
        const out = await searchWithFallback(
            [
                provider('exa', async () => {
                    throw new Error('exa_http_500')
                }),
                provider('tavily', async () => [HIT]),
            ],
            { query: 'q', limit: 5 },
            noopHttp,
            log
        )
        expect(out.provider).toBe('tavily')
        expect(log).toHaveBeenCalledWith(
            'warn',
            'web_search.provider_failed',
            expect.objectContaining({ provider: 'exa', error: 'exa_http_500' })
        )
    })

    it('throws web_search_all_providers_failed naming the providers tried (without raw err.message) when all fail', async () => {
        const log = vi.fn()
        await expect(
            searchWithFallback(
                [
                    provider('exa', async () => {
                        throw new Error('exa_http_500')
                    }),
                    provider('brave', async () => {
                        throw new Error('fetch failed: https://api.search.brave.com/...?q=sensitive')
                    }),
                ],
                { query: 'sensitive', limit: 5 },
                noopHttp,
                log
            )
        ).rejects.toThrow(/web_search_all_providers_failed: tried exa, brave/)
        // Per-provider warns keep the structured error code intact and the URL
        // (which may embed the user query in `?q=…`) is scrubbed to `<url>`.
        // The whole point is that the warn log lands in stdout + Kafka + any
        // downstream SIEM with a longer retention than the LLM-visible result,
        // so we don't want the query in it either.
        const braveCall = log.mock.calls.find((c) => c[2]?.provider === 'brave')
        expect(braveCall?.[2]?.error).not.toContain('sensitive')
        expect(braveCall?.[2]?.error).toContain('<url>')
    })

    it('does not echo raw provider error messages (which can embed the user query) into the thrown aggregate', async () => {
        let captured: Error | undefined
        try {
            await searchWithFallback(
                [
                    provider('brave', async () => {
                        throw new Error('fetch failed: https://api.search.brave.com/?q=top-secret-query')
                    }),
                ],
                { query: 'top-secret-query', limit: 5 },
                noopHttp,
                noopLog
            )
        } catch (e) {
            captured = e as Error
        }
        expect(captured?.message).not.toContain('top-secret-query')
        expect(captured?.message).toMatch(/^web_search_all_providers_failed: tried brave/)
    })
})
