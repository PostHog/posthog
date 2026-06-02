import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'

import { useAvailableFeatures } from '~/mocks/features'
import { handlers } from '~/mocks/handlers'
import { Mocks, mocksToHandlers } from '~/mocks/utils'

const isSilencedHost = (hostname: string): boolean =>
    hostname === 'posthog.com' ||
    hostname.endsWith('.posthog.com') ||
    hostname === 'gravatar.com' ||
    hostname.endsWith('.gravatar.com')

// Catch-all fallback for any request not matched by a specific (useMocks) or default handler.
// It returns a clean network error instead of letting MSW v2 pass the request through to real
// `fetch`, which crashes the jsdom test env with "originalResponse.clone is not a function".
// Runtime `useMocks()` handlers are prepended and the default `handlers` come first, so both take
// priority — this only ever catches genuinely-unhandled requests (the app then fails gracefully,
// as it did under MSW v1's network error). We still log the miss to aid debugging.
const unhandledRequestFallback = http.all(/.*/, ({ request }) => {
    const { hostname } = new URL(request.url)
    if (!isSilencedHost(hostname)) {
        console.warn(`[MSW] Unhandled ${request.method} ${request.url}`)
    }
    return HttpResponse.error()
})

export const mswServer = setupServer(...handlers, unhandledRequestFallback)
export const useMocks = (mocks: Mocks): void => mswServer.use(...mocksToHandlers(mocks))

window.confirm = jest.fn()

beforeAll(() => {
    useAvailableFeatures([])
    mswServer.listen()
})
afterEach(() => mswServer.resetHandlers())
afterAll(() => mswServer.close())
