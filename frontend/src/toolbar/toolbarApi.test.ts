import { toolbarApi } from '~/toolbar/toolbarApi'
import { toolbarFetch } from '~/toolbar/toolbarFetch'
import { captureToolbarException } from '~/toolbar/toolbarPosthogJS'

jest.mock('~/toolbar/toolbarFetch', () => ({
    toolbarFetch: jest.fn(),
}))
jest.mock('~/toolbar/toolbarPosthogJS', () => ({
    captureToolbarException: jest.fn(),
}))

describe('toolbarApi', () => {
    const mockToolbarFetch = toolbarFetch as jest.Mock
    const mockCapture = captureToolbarException as jest.Mock

    beforeEach(() => {
        jest.clearAllMocks()
    })

    it('treats a transient network failure as expected: no exception reported', async () => {
        // A flaky connection (Safari's "Load failed", offline, CORS) makes `fetch` reject.
        mockToolbarFetch.mockRejectedValueOnce(new TypeError('Load failed'))

        const result = await toolbarApi.get('/api/projects/@current/web_experiments/', { context: 'load_experiments' })

        expect(result).toMatchObject({ ok: false, status: 0, error: { isNetworkError: true } })
        expect(mockCapture).not.toHaveBeenCalled()
    })

    it('still reports a genuine server error as an exception', async () => {
        mockToolbarFetch.mockResolvedValueOnce({
            status: 503,
            ok: false,
            json: async () => ({ detail: 'service unavailable' }),
        })

        const result = await toolbarApi.get('/api/projects/@current/web_experiments/', { context: 'load_experiments' })

        expect(result.ok).toBe(false)
        expect(mockCapture).toHaveBeenCalledTimes(1)
    })
})
