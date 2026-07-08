import { toolbarApi } from '~/toolbar/toolbarApi'
import { toolbarFetch } from '~/toolbar/toolbarFetch'
import { captureToolbarException } from '~/toolbar/toolbarPosthogJS'

jest.mock('~/toolbar/toolbarFetch', () => ({
    toolbarFetch: jest.fn(),
}))

// Keep the real toolbar posthog-js instance but spy on the exception capture helper so we
// can assert what does and doesn't get reported to error tracking.
jest.mock('~/toolbar/toolbarPosthogJS', () => ({
    ...jest.requireActual('~/toolbar/toolbarPosthogJS'),
    captureToolbarException: jest.fn(),
}))

const mockToolbarFetch = toolbarFetch as jest.Mock
const mockCapture = captureToolbarException as jest.Mock

describe('toolbarApi request failure reporting', () => {
    beforeEach(() => {
        jest.clearAllMocks()
    })

    it('does not report network-level failures as exceptions', async () => {
        // A rejected fetch is the ad-blocker/offline/wrapped-`window.fetch` case — pure noise.
        mockToolbarFetch.mockRejectedValueOnce(new TypeError('Failed to fetch'))

        const result = await toolbarApi.actions.list({ context: 'load_actions' })

        if (result.ok) {
            throw new Error('expected the request to fail')
        }
        expect(result.error.isNetworkError).toBe(true)
        expect(result.error.status).toBe(0)
        expect(mockCapture).not.toHaveBeenCalled()
    })

    it('still reports server errors as exceptions', async () => {
        mockToolbarFetch.mockResolvedValueOnce({
            ok: false,
            status: 500,
            json: async () => ({ detail: 'boom' }),
        })

        const result = await toolbarApi.actions.list({ context: 'load_actions' })

        if (result.ok) {
            throw new Error('expected the request to fail')
        }
        expect(result.error.status).toBe(500)
        expect(mockCapture).toHaveBeenCalledTimes(1)
    })
})
