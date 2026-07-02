import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'
import { afterAll, afterEach, beforeAll, describe, expect, it } from 'vitest'

import { createClient, type PostHogClient } from '../src/index'

const HOST = 'https://app.example.test'
let lastMethod = ''
let lastPath = ''
let lastBody: unknown

const server = setupServer(
    http.all(`${HOST}/*`, async ({ request }) => {
        lastMethod = request.method
        lastPath = new URL(request.url).pathname
        lastBody =
            request.method === 'GET'
                ? undefined
                : await request
                      .clone()
                      .json()
                      .catch(() => undefined)
        return HttpResponse.json({ results: [], id: 1 })
    })
)

beforeAll(() => server.listen({ onUnhandledRequest: 'error' }))
afterEach(() => (lastBody = undefined))
afterAll(() => server.close())

function client(): PostHogClient {
    return createClient({ apiKey: 'k', host: HOST, projectId: 42, organizationId: 'org_1' })
}

// Each case exercises one generated method and asserts the HTTP method + path the
// SDK builds from the parsed MCP handler. Covers CRUD, path params, project vs
// organization scope, and the soft-delete PATCH translation.
type Case = [name: string, run: (c: PostHogClient) => Promise<unknown>, method: string, path: string]

const CASES: Case[] = [
    ['featureFlags.list', (c) => c.featureFlags.list(), 'GET', '/api/projects/42/feature_flags/'],
    ['featureFlags.get', (c) => c.featureFlags.get({ id: 3 }), 'GET', '/api/projects/42/feature_flags/3/'],
    ['featureFlags.create', (c) => c.featureFlags.create({ key: 'x' }), 'POST', '/api/projects/42/feature_flags/'],
    [
        'featureFlags.update',
        (c) => c.featureFlags.update({ id: 3, name: 'y' }),
        'PATCH',
        '/api/projects/42/feature_flags/3/',
    ],
    ['featureFlags.delete', (c) => c.featureFlags.delete({ id: 3 }), 'PATCH', '/api/projects/42/feature_flags/3/'],
    ['dashboards.get', (c) => c.dashboards.get({ id: 9 }), 'GET', '/api/projects/42/dashboards/9/'],
    ['dashboards.list', (c) => c.dashboards.list(), 'GET', '/api/projects/42/dashboards/'],
    ['insights.get', (c) => c.insights.get({ id: 4 }), 'GET', '/api/projects/42/insights/4/'],
    ['experiments.list', (c) => c.experiments.list(), 'GET', '/api/projects/42/experiments/'],
    ['cohorts.list', (c) => c.cohorts.list(), 'GET', '/api/projects/42/cohorts/'],
    ['organization.get', (c) => c.organization.get({ id: 'org_1' }), 'GET', '/api/organizations/org_1/'],
    [
        'query.run',
        (c) => c.query.run({ query: { kind: 'HogQLQuery', query: 'select 1' } }),
        'POST',
        '/api/environments/42/query/',
    ],
]

describe('@posthog/sdk generated resource surface', () => {
    it.each(CASES)('%s issues the expected method + path', async (_name, run, method, path) => {
        await run(client())
        expect(lastMethod).toBe(method)
        expect(lastPath).toBe(path)
    })

    it('featureFlags.delete sends the soft-delete body', async () => {
        await client().featureFlags.delete({ id: 3 })
        expect(lastBody).toEqual({ deleted: true })
    })

    it('query.trends injects the query kind and posts to the environments query endpoint', async () => {
        await client().query.trends({ series: [{ event: '$pageview' }], dateRange: { date_from: '-7d' } })
        expect(lastPath).toBe('/api/environments/42/query/')
        expect(lastBody).toEqual({
            query: {
                kind: 'TrendsQuery',
                series: [{ event: '$pageview' }],
                dateRange: { date_from: '-7d' },
            },
        })
    })

    it('query.trendsActors wraps the source in an ActorsQuery with the trends projection', async () => {
        await client().query.trendsActors({
            source: { kind: 'TrendsQuery', series: [{ event: '$pageview' }] },
            day: '2024-01-15',
            series: 0,
        })
        expect(lastPath).toBe('/api/environments/42/query/')
        expect(lastBody).toEqual({
            query: {
                kind: 'ActorsQuery',
                source: {
                    kind: 'InsightActorsQuery',
                    source: { kind: 'TrendsQuery', series: [{ event: '$pageview' }] },
                    day: '2024-01-15',
                    series: 0,
                },
                select: ['actor', 'event_count'],
                orderBy: ['event_count DESC', 'actor_id DESC'],
                limit: 100,
            },
        })
    })

    it('exposes many resources, each a class instance with async methods', () => {
        const c = client()
        // Sanity: the composed client surfaces a broad, non-trivial resource set.
        const resourceKeys = Object.keys(c)
        expect(resourceKeys.length).toBeGreaterThan(100)
        expect(typeof c.featureFlags.list).toBe('function')
        expect(typeof c.dashboards.get).toBe('function')
    })
})
