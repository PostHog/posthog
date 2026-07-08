import { Value } from 'typebox/value'

import type { HttpFetcher, ToolContext } from '@posthog/agent-shared'

import { makeCtx } from '../test-helpers'
import { posthogQueryV1 } from './posthog-query.v1'

/** Pre-resolved posthog identity, as the dispatch wrapper threads in for a tool
 *  declaring a posthog `requires.provider`. */
const posthogIdentity: ToolContext['resolvedIdentities'] = {
    posthog: { credential: { kind: 'posthog_bearer', token: 'tok' }, allowedHosts: ['localhost:8010'] },
}

function fetchReturning(payload: unknown): { http: HttpFetcher; calls: Array<{ url: string; body: unknown }> } {
    const calls: Array<{ url: string; body: unknown }> = []
    const http: HttpFetcher = {
        fetch: async (url, init) => {
            calls.push({ url: String(url), body: init?.body ? JSON.parse(String(init.body)) : undefined })
            return new Response(JSON.stringify(payload), {
                status: 200,
                headers: { 'content-type': 'application/json' },
            })
        },
    }
    return { http, calls }
}

describe('@posthog/query', () => {
    it('runs HogQL as the connected user and zips columns into keyed rows', async () => {
        const { http, calls } = fetchReturning({
            results: [
                [1, 'a'],
                [2, 'b'],
            ],
            columns: ['id', 'name'],
        })
        const logs: Array<{ msg: string; meta?: Record<string, unknown> }> = []
        const ctx = makeCtx({
            resolvedIdentities: posthogIdentity,
            http,
            log: (_level, msg, meta) => logs.push({ msg, meta }),
        })

        const out = await posthogQueryV1.run({ project_id: 7, query: 'select 1' }, ctx)

        expect(out).toEqual({
            rows: [
                { id: 1, name: 'a' },
                { id: 2, name: 'b' },
            ],
            columns: ['id', 'name'],
        })
        // Targets the explicit project's query endpoint with a HogQLQuery body.
        expect(calls[0].url).toBe('http://localhost:8010/api/projects/7/query/')
        expect(calls[0].body).toEqual({ query: { kind: 'HogQLQuery', query: 'select 1' } })
        expect(logs[0]).toEqual({ msg: 'hogql.executed', meta: { query: 'select 1', row_count: 2 } })
    })

    it('targets whatever project_id the agent passes (no principal coupling)', async () => {
        const { http, calls } = fetchReturning({ results: [], columns: [] })
        const ctx = makeCtx({ resolvedIdentities: posthogIdentity, http })
        await posthogQueryV1.run({ project_id: 42, query: 'select 1' }, ctx)
        expect(calls[0].url).toBe('http://localhost:8010/api/projects/42/query/')
    })

    it('surfaces an unavailable posthog identity', async () => {
        const { http } = fetchReturning({ results: [], columns: [] })
        const ctx = makeCtx({
            identity: {
                resolve: async () => ({ kind: 'unavailable', provider: 'posthog', reason: 'principal_not_linkable' }),
            },
            http,
        })
        await expect(posthogQueryV1.run({ project_id: 1, query: 'select 1' }, ctx)).rejects.toThrow(
            /posthog_credentials_unavailable/
        )
    })

    it('validates args via TypeBox schema', () => {
        // `project_id` is required now — a query without it must fail validation.
        expect(Value.Check(posthogQueryV1.schema.args, { query: 'select 1' })).toBe(false)
        expect(Value.Check(posthogQueryV1.schema.args, { project_id: 1, query: '' })).toBe(false)
        expect(Value.Check(posthogQueryV1.schema.args, { project_id: 1, query: 'select 1' })).toBe(true)
    })
})
