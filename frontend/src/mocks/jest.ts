import { setupServer } from 'msw/node'

import { useAvailableFeatures } from '~/mocks/features'
import { EMPTY_PAGINATED_RESPONSE, handlers } from '~/mocks/handlers'
import { Mocks, mocksToHandlers } from '~/mocks/utils'

// Jest-only defaults. Under jsdom an unhandled request hits the never-resolving fetch stub
// (see beforeAll), so any logic that awaits one of these on mount would hang
// toFinishAllListeners. These live here rather than in the shared `handlers` so the Storybook
// MSW worker — which serves the same `handlers` to a real browser — is left untouched. Appended
// after `handlers` so an existing matching handler still wins, and `server.use()` (useMocks)
// still overrides them per test.
const jestOnlyDefaultHandlers = mocksToHandlers({
    get: {
        '/api/projects/:team_id/product_tours/': EMPTY_PAGINATED_RESPONSE,
        '/api/environments/:team_id/integrations/': EMPTY_PAGINATED_RESPONSE,
        '/api/environments/:team_id/llm_analytics/evaluation_config/': { active_provider_key: null },
        '/api/environments/:team_id/taggers/': EMPTY_PAGINATED_RESPONSE,
        '/api/projects/:team_id/event_definitions/primary_properties/': { primary_properties: {} },
        '/api/environments/:team_id/default_release_conditions/': { default_groups: [], enabled: false },
        // The unhandled-request floor (a paginated `{ results: [] }`) is the wrong shape here and
        // would crash UsedInBanner, which reads `feature_flags.results` & co.
        '/api/projects/:team_id/cohorts/:id/used_in/': {
            feature_flags: { results: [], total: 0, has_more: false },
            insights: { results: [], total: 0, has_more: false },
            cohorts: { results: [], total: 0, has_more: false },
        },
    },
})

export const mswServer = setupServer(...handlers, ...jestOnlyDefaultHandlers)
export const useMocks = (mocks: Mocks): void => mswServer.use(...mocksToHandlers(mocks))

window.confirm = jest.fn()

beforeAll(() => {
    useAvailableFeatures([])
    // MSW passes unhandled requests through to the "real" global fetch. Under MSW v2 in jsdom that
    // passthrough resolves a response the interceptor then fails to clone ("originalResponse.clone
    // is not a function"), crashing the whole file. We can't passthrough. The two obvious stubs are
    // both worse at scale: a never-resolving stub makes any awaited unmocked load hang
    // toFinishAllListeners, and a rejecting stub turns every fire-and-forget request into an
    // unhandled "Failed to fetch" rejection that settles after teardown and OOMs the worker.
    // Instead resolve a benign, cloneable, empty paginated response: awaited loads complete (no
    // hang), loaders succeed with empty data (no rejection, no post-teardown console), and the 2xx
    // path never touches `location` (no "location is not defined"). A test that needs real data
    // from an endpoint mocks it explicitly via useMocks; this is only the floor for the rest.
    global.fetch = (() =>
        Promise.resolve(
            new Response(JSON.stringify({ results: [], count: 0, next: null, previous: null }), {
                status: 200,
                headers: { 'content-type': 'application/json' },
            })
        )) as typeof fetch
    // Silent: suites run to completion, so warning on every unhandled request would flood output.
    mswServer.listen({ onUnhandledRequest: () => {} })
})
afterEach(() => mswServer.resetHandlers())
afterAll(() => mswServer.close())
