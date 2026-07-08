import { toolbarApi } from '~/toolbar/toolbarApi'
import { toolbarFetch } from '~/toolbar/toolbarFetch'
import { captureToolbarException } from '~/toolbar/toolbarPosthogJS'

jest.mock('~/toolbar/toolbarFetch', () => ({ toolbarFetch: jest.fn() }))
jest.mock('~/toolbar/toolbarPosthogJS', () => ({ captureToolbarException: jest.fn() }))

describe('toolbarApi error observability', () => {
    const mockToolbarFetch = toolbarFetch as jest.Mock
    const mockCapture = captureToolbarException as jest.Mock

    beforeEach(() => {
        jest.clearAllMocks()
        jest.spyOn(console, 'warn').mockImplementation()
        jest.spyOn(console, 'error').mockImplementation()
    })

    afterEach(() => {
        jest.restoreAllMocks()
    })

    // Network-level failures (fetch rejects: ad blockers, CORS, offline, customer fetch
    // wrappers) are expected outcomes the caller soft-fails on — they must stay logged
    // without being escalated to error tracking, where they'd bury genuine failures.
    it('does not report network-level failures as exceptions', async () => {
        mockToolbarFetch.mockRejectedValueOnce(new TypeError('Failed to fetch'))

        const result = await toolbarApi.get('/api/projects/@current/web_experiments/', { context: 'load_experiments' })

        expect(result.ok).toBe(false)
        if (result.ok) {
            throw new Error('expected a failure result')
        }
        expect(result.status).toBe(0)
        expect(result.error.isNetworkError).toBe(true)
        expect(mockCapture).not.toHaveBeenCalled()
    })

    // Server errors are genuinely unexpected and must still reach error tracking.
    it('reports server (5xx) failures as exceptions', async () => {
        mockToolbarFetch.mockResolvedValueOnce({ ok: false, status: 500, json: async () => ({ detail: 'boom' }) })

        const result = await toolbarApi.get('/api/projects/@current/web_experiments/', { context: 'load_experiments' })

        expect(result.ok).toBe(false)
        expect(mockCapture).toHaveBeenCalledTimes(1)
    })
})
