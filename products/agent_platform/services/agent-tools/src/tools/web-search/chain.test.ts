import { describe, expect, it, vi } from 'vitest'

import type { Logger, WebSearchProviderName } from '@posthog/agent-shared'

import { buildWebSearchProviders } from './chain'

const ALL_KEYS: Record<WebSearchProviderName, string | undefined> = { exa: 'e', tavily: 't', brave: 'b' }
const NO_KEYS: Record<WebSearchProviderName, string | undefined> = {
    exa: undefined,
    tavily: undefined,
    brave: undefined,
}
const onlyKey = (
    overrides: Partial<Record<WebSearchProviderName, string>>
): Record<WebSearchProviderName, string | undefined> => ({
    ...NO_KEYS,
    ...overrides,
})

describe('buildWebSearchProviders', () => {
    it('returns an empty chain when no keys are set', () => {
        expect(buildWebSearchProviders({ keys: NO_KEYS })).toEqual([])
    })

    it('puts the configured primary first, then keyed providers in natural order', () => {
        const chain = buildWebSearchProviders({ primary: 'brave', keys: ALL_KEYS })
        expect(chain.map((p) => p.name)).toEqual(['brave', 'exa', 'tavily'])
    })

    it('honours an explicit ordered fallback list after the primary', () => {
        const chain = buildWebSearchProviders({ primary: 'exa', fallbacks: 'brave,tavily', keys: ALL_KEYS })
        expect(chain.map((p) => p.name)).toEqual(['exa', 'brave', 'tavily'])
    })

    it('skips a primary whose key is missing rather than failing', () => {
        const chain = buildWebSearchProviders({ primary: 'exa', keys: onlyKey({ tavily: 't' }) })
        expect(chain.map((p) => p.name)).toEqual(['tavily'])
    })

    it('de-duplicates a provider listed as both primary and fallback', () => {
        const chain = buildWebSearchProviders({ primary: 'exa', fallbacks: 'exa,brave', keys: ALL_KEYS })
        expect(chain.map((p) => p.name)).toEqual(['exa', 'brave'])
    })

    it('ignores unknown provider ids and whitespace/casing in config', () => {
        const chain = buildWebSearchProviders({ primary: ' EXA ', fallbacks: 'bogus, Brave ', keys: ALL_KEYS })
        expect(chain.map((p) => p.name)).toEqual(['exa', 'brave'])
    })

    it('falls back to every keyed provider when no primary or fallbacks are given', () => {
        const chain = buildWebSearchProviders({ keys: onlyKey({ tavily: 't', brave: 'b' }) })
        expect(chain.map((p) => p.name)).toEqual(['tavily', 'brave'])
    })

    it('treats whitespace-only API keys as unset', () => {
        const chain = buildWebSearchProviders({ keys: onlyKey({ exa: '   ', tavily: 't' }) })
        expect(chain.map((p) => p.name)).toEqual(['tavily'])
    })

    it('warns once per unrecognised fallback id so a misconfig is self-diagnosing', () => {
        const warn = vi.fn()
        const log = { warn } as unknown as Logger
        const chain = buildWebSearchProviders({ primary: 'exa', fallbacks: 'bogus, brave', keys: ALL_KEYS }, log)
        expect(chain.map((p) => p.name)).toEqual(['exa', 'brave'])
        expect(warn).toHaveBeenCalledTimes(1)
        expect(warn).toHaveBeenCalledWith(
            expect.objectContaining({ name: 'bogus' }),
            expect.stringContaining('unknown_provider')
        )
    })

    it('warns when the configured primary has no API key', () => {
        const warn = vi.fn()
        const log = { warn } as unknown as Logger
        const chain = buildWebSearchProviders({ primary: 'exa', keys: onlyKey({ tavily: 't' }) }, log)
        expect(chain.map((p) => p.name)).toEqual(['tavily'])
        expect(warn).toHaveBeenCalledWith(
            expect.objectContaining({ provider: 'exa' }),
            expect.stringContaining('primary_key_missing')
        )
    })
})
