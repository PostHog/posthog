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
    },
})

export const mswServer = setupServer(...handlers, ...jestOnlyDefaultHandlers)
export const useMocks = (mocks: Mocks): void => mswServer.use(...mocksToHandlers(mocks))

window.confirm = jest.fn()

beforeAll(() => {
    useAvailableFeatures([])
    // MSW passes unhandled requests through to the "real" global fetch. In the jsdom test env
    // that real fetch can resolve with a response the MSW v2 interceptor then fails to clone
    // ("originalResponse.clone is not a function"), crashing the whole test file. Replace it with
    // a never-resolving stub so unhandled requests just hang (as a real network call to a
    // non-existent server effectively does). Hanging — rather than erroring — is deliberate: a
    // resolved/rejected response lets fire-and-forget requests settle after jsdom teardown and
    // throw "location is not defined" / "Cannot log after tests are done", which OOMs jest workers
    // across a large shard. A loader the test actually awaits should be mocked explicitly so it
    // doesn't hang `toFinishAllListeners`. Handled requests never reach here — MSW only calls this
    // for genuine passthrough.
    global.fetch = (() => new Promise<Response>(() => {})) as typeof fetch
    // Silent: suites run to completion, so warning on every unhandled request would flood output.
    mswServer.listen({ onUnhandledRequest: () => {} })
})
afterEach(() => mswServer.resetHandlers())
afterAll(() => mswServer.close())
