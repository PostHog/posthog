import type { Pool } from 'pg'

import { PgTeamApiKeyResolver, TeamApiKeyNotFoundError } from './team-api-key-resolver'

interface FakeQueryArgs {
    sql: string
    values: unknown[]
}

interface FakePool {
    queries: FakeQueryArgs[]
    rows: Array<{ api_token: string | null }>
    /** Optional override that runs instead of returning `rows`. */
    onQuery?: (args: FakeQueryArgs) => Promise<{ rows: Array<{ api_token: string | null }> }>
}

// pg's Pool#query has many overloads; the resolver uses the (text, values) form
// which returns `{ rows }`. We cast through `unknown` rather than spell out the
// full overload union.
type FakePoolWithQuery = FakePool & {
    query: (text: string, values: unknown[]) => Promise<{ rows: Array<{ api_token: string | null }> }>
}

function makeFakePool(rows: Array<{ api_token: string | null }> = []): FakePoolWithQuery {
    const fake: FakePoolWithQuery = {
        queries: [],
        rows,
        async query(text, values) {
            fake.queries.push({ sql: text, values })
            if (fake.onQuery) {
                return fake.onQuery({ sql: text, values })
            }
            return { rows: fake.rows }
        },
    }
    return fake
}

describe('PgTeamApiKeyResolver', () => {
    it('returns the api_token for a known team', async () => {
        const pool = makeFakePool([{ api_token: 'phc_team1' }])
        const r = new PgTeamApiKeyResolver(pool as unknown as Pool)
        await expect(r.resolve(1)).resolves.toBe('phc_team1')
        expect(pool.queries).toHaveLength(1)
        expect(pool.queries[0].values).toEqual([1])
    })

    it('caches subsequent lookups within the TTL window', async () => {
        const pool = makeFakePool([{ api_token: 'phc_team1' }])
        const r = new PgTeamApiKeyResolver(pool as unknown as Pool, { ttlMs: 60_000 })
        await r.resolve(1)
        await r.resolve(1)
        await r.resolve(1)
        expect(pool.queries).toHaveLength(1)
    })

    it('re-reads after the TTL expires', async () => {
        const pool = makeFakePool([{ api_token: 'phc_team1' }])
        const r = new PgTeamApiKeyResolver(pool as unknown as Pool, { ttlMs: 1 })
        await r.resolve(1)
        await new Promise((res) => setTimeout(res, 5))
        await r.resolve(1)
        expect(pool.queries).toHaveLength(2)
    })

    it('invalidate() drops a single team', async () => {
        const pool = makeFakePool([{ api_token: 'phc_team1' }])
        const r = new PgTeamApiKeyResolver(pool as unknown as Pool, { ttlMs: 60_000 })
        await r.resolve(1)
        r.invalidate(1)
        await r.resolve(1)
        expect(pool.queries).toHaveLength(2)
    })

    it('throws TeamApiKeyNotFoundError for a missing team', async () => {
        const pool = makeFakePool([])
        const r = new PgTeamApiKeyResolver(pool as unknown as Pool)
        await expect(r.resolve(999)).rejects.toBeInstanceOf(TeamApiKeyNotFoundError)
    })

    it('throws TeamApiKeyNotFoundError when api_token is NULL', async () => {
        const pool = makeFakePool([{ api_token: null }])
        const r = new PgTeamApiKeyResolver(pool as unknown as Pool)
        await expect(r.resolve(1)).rejects.toBeInstanceOf(TeamApiKeyNotFoundError)
    })

    it('does not cache failures (next call retries the DB)', async () => {
        let rows: Array<{ api_token: string | null }> = []
        const pool = makeFakePool()
        pool.onQuery = async () => ({ rows })
        const r = new PgTeamApiKeyResolver(pool as unknown as Pool)
        await expect(r.resolve(1)).rejects.toBeInstanceOf(TeamApiKeyNotFoundError)
        rows = [{ api_token: 'phc_team1' }]
        await expect(r.resolve(1)).resolves.toBe('phc_team1')
        expect(pool.queries).toHaveLength(2)
    })
})
