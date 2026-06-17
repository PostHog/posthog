import { Value } from 'typebox/value'

import type { HttpFetcher, ToolContext } from '@posthog/agent-shared'

import { makeCtx } from '../test-helpers'
import { posthogQueryV1 } from './posthog-query.v1'

/** A posthog_api bearer, as the ingress verifier writes for `posthog`-auth sessions. */
const posthogCredentials: ToolContext['credentials'] = {
    resolve: async (target) => (target === 'posthog_api' ? { kind: 'posthog_bearer', token: 'tok' } : null),
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
            posthogUserTeamId: 7,
            credentials: posthogCredentials,
            http,
            log: (_level, msg, meta) => logs.push({ msg, meta }),
        })

        const out = await posthogQueryV1.run({ query: 'select 1' }, ctx)

        expect(out).toEqual({
            rows: [
                { id: 1, name: 'a' },
                { id: 2, name: 'b' },
            ],
            columns: ['id', 'name'],
        })
        // Targets the caller's team query endpoint with a HogQLQuery body.
        expect(calls[0].url).toBe('http://localhost:8010/api/projects/7/query/')
        expect(calls[0].body).toEqual({ query: { kind: 'HogQLQuery', query: 'select 1' } })
        expect(logs[0]).toEqual({ msg: 'hogql.executed', meta: { query: 'select 1', row_count: 2 } })
    })

    it('fails closed without a posthog user principal', async () => {
        const { http } = fetchReturning({ results: [], columns: [] })
        const ctx = makeCtx({ posthogUserTeamId: undefined, credentials: posthogCredentials, http })
        await expect(posthogQueryV1.run({ query: 'select 1' }, ctx)).rejects.toThrow(/posthog_user_context_required/)
    })

    it('surfaces a missing posthog credential', async () => {
        const { http } = fetchReturning({ results: [], columns: [] })
        const ctx = makeCtx({ credentials: { resolve: async () => null }, http })
        await expect(posthogQueryV1.run({ query: 'select 1' }, ctx)).rejects.toThrow(/posthog_credentials_unavailable/)
    })

    it('validates args via TypeBox schema', () => {
        expect(Value.Check(posthogQueryV1.schema.args, { query: '' })).toBe(false)
        expect(Value.Check(posthogQueryV1.schema.args, { query: 'select 1' })).toBe(true)
    })
})
