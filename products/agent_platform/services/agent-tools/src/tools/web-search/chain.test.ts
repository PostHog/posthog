import { describe, expect, it } from 'vitest'

import { buildWebSearchProviders } from './chain'

const ALL_KEYS = { exa: 'e', tavily: 't', brave: 'b' }

describe('buildWebSearchProviders', () => {
    it('returns an empty chain when no keys are set', () => {
        expect(buildWebSearchProviders({ keys: {} })).toEqual([])
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
        const chain = buildWebSearchProviders({ primary: 'exa', keys: { tavily: 't' } })
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
        const chain = buildWebSearchProviders({ keys: { tavily: 't', brave: 'b' } })
        expect(chain.map((p) => p.name)).toEqual(['tavily', 'brave'])
    })
})
