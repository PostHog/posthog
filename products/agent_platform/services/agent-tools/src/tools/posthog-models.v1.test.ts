import { describe, expect, it } from 'vitest'

import type { CatalogModel, GatewayCatalog } from '@posthog/agent-shared'

import { makeCtx } from '../test-helpers'
import { posthogListModelsV1 } from './posthog-models.v1'

function catalogOf(models: CatalogModel[]): GatewayCatalog {
    return { list: async () => models }
}

const HAIKU: CatalogModel = {
    canonical: 'anthropic/claude-haiku-4.5',
    id: 'claude-haiku-4-5-20251001',
    aliases: ['claude-haiku-4-5'],
    owned_by: 'anthropic',
    context_window: 200_000,
    pricing: { prompt: 0.000001, completion: 0.000005, cache_read: 0.0000001, cache_write: 0.00000125 },
}
const GPT: CatalogModel = {
    canonical: 'openai/gpt-5',
    id: 'gpt-5',
    aliases: [],
    owned_by: 'openai',
    context_window: 400_000,
    pricing: { prompt: 0.00000125, completion: 0.00001 },
}

describe('@posthog/agent-applications-models', () => {
    it('returns canonical id, provider, context window, and per-Mtok pricing, sorted', async () => {
        const ctx = makeCtx({ gatewayCatalog: catalogOf([GPT, HAIKU]) })
        const { models } = await posthogListModelsV1.run({}, ctx)
        expect(models.map((m) => m.model)).toEqual(['anthropic/claude-haiku-4.5', 'openai/gpt-5'])
        expect(models[0]).toEqual({
            model: 'anthropic/claude-haiku-4.5',
            provider: 'anthropic',
            context_window: 200_000,
            pricing_usd_per_mtok: { input: 1, output: 5, cache_read: 0.1, cache_write: 1.25 },
        })
        // OpenAI model has no cache_write -> omitted, not zeroed
        expect(models[1].pricing_usd_per_mtok.cache_write).toBeUndefined()
        expect(models[1].pricing_usd_per_mtok).toMatchObject({ input: 1.25, output: 10 })
    })

    it('returns an empty list (no throw) when the catalog is unavailable', async () => {
        const ctx = makeCtx({ gatewayCatalog: undefined })
        await expect(posthogListModelsV1.run({}, ctx)).resolves.toEqual({ models: [] })
    })
})
