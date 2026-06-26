import { describe, expect, it, vi } from 'vitest'

import { MODEL_POLICY_LEVELS, type ModelPolicy } from '../spec/spec'
import {
    acceptedModelIds,
    type CatalogModel,
    filterServableEntries,
    HttpGatewayCatalog,
    isModelServable,
    validateModelLevels,
    validateModelPolicy,
} from './gateway-catalog'

function model(over: Partial<CatalogModel> & Pick<CatalogModel, 'canonical' | 'id' | 'owned_by'>): CatalogModel {
    return {
        aliases: [],
        context_window: 200_000,
        pricing: { prompt: 0.000001, completion: 0.000005 },
        ...over,
    }
}

// Mirrors the live gateway: haiku is dated-only with an undated alias; sonnet
// 4.6 / opus 4.7 advertise undated ids; gpt-5 family is plain canonicals.
const CATALOG: CatalogModel[] = [
    model({
        canonical: 'anthropic/claude-haiku-4.5',
        id: 'claude-haiku-4-5-20251001',
        owned_by: 'anthropic',
        aliases: ['claude-haiku-4-5'],
    }),
    model({ canonical: 'anthropic/claude-sonnet-4.6', id: 'claude-sonnet-4-6', owned_by: 'anthropic' }),
    model({ canonical: 'anthropic/claude-opus-4.7', id: 'claude-opus-4-7', owned_by: 'anthropic' }),
    model({ canonical: 'openai/gpt-5', id: 'gpt-5', owned_by: 'openai' }),
    model({ canonical: 'openai/gpt-5-mini', id: 'gpt-5-mini', owned_by: 'openai' }),
    model({ canonical: 'openai/gpt-5-pro', id: 'gpt-5-pro', owned_by: 'openai' }),
]

describe('acceptedModelIds', () => {
    it('indexes canonical, bare suffix, id, alias, and provider-prefixed forms', () => {
        const ids = acceptedModelIds([CATALOG[0]])
        for (const form of [
            'anthropic/claude-haiku-4.5', // canonical
            'claude-haiku-4.5', // bare suffix
            'claude-haiku-4-5-20251001', // id
            'anthropic/claude-haiku-4-5-20251001', // provider + id
            'claude-haiku-4-5', // alias
            'anthropic/claude-haiku-4-5', // provider + alias (the MODEL_POLICY_LEVELS form)
        ]) {
            expect(ids.has(form)).toBe(true)
        }
        expect(ids.has('anthropic/claude-haiku-9')).toBe(false)
    })
})

describe('isModelServable', () => {
    it.each([
        ['anthropic/claude-haiku-4-5', true], // dashed undated, provider-prefixed (alias form)
        ['anthropic/claude-haiku-4.5', true], // canonical
        ['openai/gpt-5-pro', true],
        ['openai/gpt-5-thinking', false], // the drift that broke the old high tier
        ['anthropic/claude-opus-9', false],
    ])('%s -> %s', (id, expected) => {
        expect(isModelServable(CATALOG, id as string)).toBe(expected)
    })
})

describe('validateModelPolicy', () => {
    it('flags each unservable model in a manual policy with a pointer', () => {
        const policy: ModelPolicy = {
            mode: 'manual',
            models: [{ model: 'anthropic/claude-haiku-4-5' }, { model: 'openai/gpt-foo' }, { model: 'openai/gpt-5' }],
            optimize_for: 'cost',
        }
        const issues = validateModelPolicy(policy, CATALOG)
        expect(issues).toHaveLength(1)
        expect(issues[0]).toMatchObject({ model: 'openai/gpt-foo', pointer: 'spec.models.models[1].model' })
    })

    it('accepts an auto policy whose level has at least one servable member', () => {
        expect(validateModelPolicy({ mode: 'auto', level: 'high', optimize_for: 'cost' }, CATALOG)).toEqual([])
    })

    it('flags an auto policy only when the whole level is unservable', () => {
        const issues = validateModelPolicy({ mode: 'auto', level: 'high', optimize_for: 'cost' }, [CATALOG[3]]) // only openai/gpt-5
        // high = [opus-4-7, gpt-5-pro, sonnet-4-6]; none is openai/gpt-5 → whole level dead
        expect(issues).toHaveLength(1)
        expect(issues[0].pointer).toBe('spec.models.level')
    })

    it('fails open on servability when the catalog is empty (unreachable gateway)', () => {
        // `made/up` is well-formatted; absent the catalog we can't say if it's served,
        // so we let it through rather than blocking authoring.
        expect(
            validateModelPolicy({ mode: 'manual', models: [{ model: 'made/up' }], optimize_for: 'cost' }, [])
        ).toEqual([])
    })

    it('still flags a malformed manual model id even when the catalog is empty', () => {
        // Format check runs unconditionally — a bare id like `haiku-4-5` will 400 at
        // the gateway regardless of catalog state, so catching it at freeze is
        // strictly more useful than waiting for the first session to fail.
        const issues = validateModelPolicy(
            { mode: 'manual', models: [{ model: 'haiku-4-5' }], optimize_for: 'cost' },
            []
        )
        expect(issues).toHaveLength(1)
        expect(issues[0]).toMatchObject({
            model: 'haiku-4-5',
            pointer: 'spec.models.models[0].model',
            reason: expect.stringContaining('provider'),
        })
    })

    it('reports only the format error (not also "not served") when a model id is malformed', () => {
        // Otherwise the author sees two errors for the same entry and the
        // servability one is misleading (gateway will reject the format first).
        const issues = validateModelPolicy(
            { mode: 'manual', models: [{ model: 'haiku-4-5' }], optimize_for: 'cost' },
            CATALOG
        )
        expect(issues).toHaveLength(1)
        expect(issues[0].reason).toMatch(/provider/)
    })
})

describe('validateModelLevels', () => {
    it('passes when every curated tier member is served (guards MODEL_POLICY_LEVELS drift)', () => {
        const full = [
            ...CATALOG,
            // include the remaining tier members so all of low/medium/high resolve
        ]
        const issues = validateModelLevels(full)
        // CATALOG already covers haiku-4-5, gpt-5-mini, sonnet-4-6, gpt-5, opus-4-7, gpt-5-pro
        // which is exactly every member of MODEL_POLICY_LEVELS.
        expect(issues).toEqual([])
    })

    it('reports the dead tier member when a tier drifts off the catalog', () => {
        const withoutGpt5Pro = CATALOG.filter((m) => m.canonical !== 'openai/gpt-5-pro')
        const issues = validateModelLevels(withoutGpt5Pro)
        expect(issues).toEqual([
            {
                model: 'openai/gpt-5-pro',
                pointer: 'MODEL_POLICY_LEVELS.high',
                reason: 'tier member not served by the gateway',
            },
        ])
    })

    it('the committed MODEL_POLICY_LEVELS only references models present in this fixture', () => {
        // Belt-and-suspenders: the curated constant must be a subset of what we
        // model as served, so adding a new tier member without a catalog entry
        // fails here. (A live-catalog version of this runs in agent-tests e2e.)
        const accepted = acceptedModelIds(CATALOG)
        const all = Object.values(MODEL_POLICY_LEVELS).flat()
        expect(all.filter((m) => !accepted.has(m))).toEqual([])
    })
})

describe('filterServableEntries', () => {
    it('drops unservable entries', () => {
        const kept = filterServableEntries([{ model: 'openai/gpt-5' }, { model: 'openai/gpt-gone' }], CATALOG)
        expect(kept).toEqual([{ model: 'openai/gpt-5' }])
    })

    it('returns the original list when filtering would empty it (never strand a session)', () => {
        const entries = [{ model: 'openai/gpt-gone' }]
        expect(filterServableEntries(entries, CATALOG)).toBe(entries)
    })

    it('returns the original list when the catalog is empty', () => {
        const entries = [{ model: 'anything' }]
        expect(filterServableEntries(entries, [])).toBe(entries)
    })
})

describe('HttpGatewayCatalog', () => {
    const wire = {
        data: [
            {
                id: 'claude-haiku-4-5-20251001',
                canonical: 'anthropic/claude-haiku-4.5',
                owned_by: 'anthropic',
                context_window: 200000,
                aliases: ['claude-haiku-4-5'],
                pricing: {
                    prompt: '0.000001',
                    completion: '0.000005',
                    cache_read: '0.0000001',
                    cache_write: '0.00000125',
                },
            },
            // a malformed row (no pricing) is dropped, not fatal
            { id: 'broken', canonical: 'x/broken', owned_by: 'x' },
        ],
    }
    const okResponse = (): Response => ({ ok: true, status: 200, json: async () => wire }) as unknown as Response

    it('parses /models, drops malformed rows, and converts decimal-string pricing to numbers', async () => {
        const fetch = vi.fn().mockResolvedValue(okResponse())
        const cat = new HttpGatewayCatalog({ baseUrl: 'http://gw/v1', bearer: 'phs_x', http: { fetch } })
        const models = await cat.list()
        expect(models).toHaveLength(1)
        expect(models[0]).toMatchObject({ canonical: 'anthropic/claude-haiku-4.5', context_window: 200000 })
        expect(models[0].pricing).toEqual({
            prompt: 0.000001,
            completion: 0.000005,
            cache_read: 0.0000001,
            cache_write: 0.00000125,
        })
        // hit /v1/models with the bearer
        expect(fetch).toHaveBeenCalledWith('http://gw/v1/models', expect.objectContaining({ method: 'GET' }))
        expect(fetch.mock.calls[0][1].headers.Authorization).toBe('Bearer phs_x')
    })

    it('caches within the TTL (one fetch for two calls)', async () => {
        const fetch = vi.fn().mockResolvedValue(okResponse())
        const cat = new HttpGatewayCatalog({ baseUrl: 'http://gw/v1', http: { fetch }, ttlMs: 10_000 })
        await cat.list()
        await cat.list()
        expect(fetch).toHaveBeenCalledTimes(1)
    })

    it('fails open: serves [] on the first failed fetch rather than throwing', async () => {
        const fetch = vi.fn().mockResolvedValue({ ok: false, status: 503 } as unknown as Response)
        const cat = new HttpGatewayCatalog({ baseUrl: 'http://gw/v1', http: { fetch } })
        await expect(cat.list()).resolves.toEqual([])
    })

    it('serves last-good through a transient failure after a successful fetch', async () => {
        const fetch = vi
            .fn()
            .mockResolvedValueOnce(okResponse())
            .mockResolvedValueOnce({ ok: false, status: 503 } as unknown as Response)
        const cat = new HttpGatewayCatalog({ baseUrl: 'http://gw/v1', http: { fetch }, ttlMs: 0 })
        const first = await cat.list()
        const second = await cat.list() // TTL 0 forces a refetch which fails
        expect(second).toEqual(first)
        expect(second).toHaveLength(1)
    })
})
