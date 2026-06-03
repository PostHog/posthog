import { setupServer } from 'msw/node'

import { useAvailableFeatures } from '~/mocks/features'
import { handlers } from '~/mocks/handlers'
import { Mocks, mocksToHandlers } from '~/mocks/utils'

export const mswServer = setupServer(...handlers)
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
