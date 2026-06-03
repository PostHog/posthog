import { setupServer } from 'msw/node'

import { useAvailableFeatures } from '~/mocks/features'
import { handlers } from '~/mocks/handlers'
import { Mocks, mocksToHandlers } from '~/mocks/utils'

export const mswServer = setupServer(...handlers)
export const useMocks = (mocks: Mocks): void => mswServer.use(...mocksToHandlers(mocks))

window.confirm = jest.fn()

beforeAll(() => {
    useAvailableFeatures([])
    mswServer.listen({
        onUnhandledRequest(request) {
            const { hostname } = new URL(request.url)
            // Silence external requests entirely
            if (
                hostname === 'posthog.com' ||
                hostname.endsWith('.posthog.com') ||
                hostname === 'gravatar.com' ||
                hostname.endsWith('.gravatar.com')
            ) {
                return
            }
            // Single-line warning instead of verbose multi-line stack trace
            console.warn(`[MSW] Unhandled ${request.method} ${request.url}`)
        },
    })
})
afterEach(() => mswServer.resetHandlers())
afterAll(() => mswServer.close())
