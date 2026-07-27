import { describe, expect, it, vi } from 'vitest'

import type { WebSearchInput, WebSearchProvider, WebSearchResult } from '@posthog/agent-shared'

import { makeCtx } from '../../test-helpers'
import { webSearchV1 } from './web-search.v1'

const HIT: WebSearchResult = { title: 't', url: 'https://x', snippet: 's' }

function provider(
    name: WebSearchProvider['name'],
    impl: (input: WebSearchInput) => Promise<WebSearchResult[]>
): WebSearchProvider {
    return { name, search: (input) => impl(input) }
}

describe('@posthog/web-search', () => {
    it('returns the serving provider and its results', async () => {
        const out = await webSearchV1.run(
            { query: 'posthog' },
            makeCtx({ webSearchProviders: [provider('exa', async () => [HIT])] })
        )
        expect(out).toEqual({ provider: 'exa', results: [HIT] })
    })

    it('defaults limit to 10 and forwards the query to the provider', async () => {
        const search = vi.fn(async () => [HIT])
        await webSearchV1.run({ query: 'flags' }, makeCtx({ webSearchProviders: [provider('exa', search)] }))
        expect(search).toHaveBeenCalledWith({ query: 'flags', limit: 10 })
    })

    it('passes an explicit limit through to the provider', async () => {
        const search = vi.fn(async () => [HIT])
        await webSearchV1.run({ query: 'flags', limit: 5 }, makeCtx({ webSearchProviders: [provider('exa', search)] }))
        expect(search).toHaveBeenCalledWith({ query: 'flags', limit: 5 })
    })

    it('falls through to a fallback provider when the primary throws', async () => {
        const out = await webSearchV1.run(
            { query: 'posthog' },
            makeCtx({
                webSearchProviders: [
                    provider('exa', async () => {
                        throw new Error('exa_http_500')
                    }),
                    provider('tavily', async () => [HIT]),
                ],
            })
        )
        expect(out.provider).toBe('tavily')
    })

    it('throws web_search_not_configured when no providers are wired', async () => {
        await expect(webSearchV1.run({ query: 'posthog' }, makeCtx({}))).rejects.toThrow(/web_search_not_configured/)
    })
})
