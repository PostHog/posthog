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
        onUnhandledRequest(req) {
            const url = req.url.toString()
            // Silence external requests entirely
            if (url.includes('us.i.posthog.com') || url.includes('gravatar.com')) {
                return
            }
            // Single-line warning instead of verbose multi-line stack trace
            console.warn(`[MSW] Unhandled ${req.method} ${url}`)
        },
    })
})
afterEach(() => mswServer.resetHandlers())
afterAll(() => mswServer.close())
