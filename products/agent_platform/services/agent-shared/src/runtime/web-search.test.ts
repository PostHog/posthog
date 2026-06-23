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

    it('throws web_search_all_providers_failed with each error when every provider fails', async () => {
        await expect(
            searchWithFallback(
                [
                    provider('exa', async () => {
                        throw new Error('exa_http_500')
                    }),
                    provider('brave', async () => {
                        throw new Error('brave_http_429')
                    }),
                ],
                { query: 'q', limit: 5 },
                noopHttp,
                noopLog
            )
        ).rejects.toThrow(/web_search_all_providers_failed: exa: exa_http_500; brave: brave_http_429/)
    })
})
