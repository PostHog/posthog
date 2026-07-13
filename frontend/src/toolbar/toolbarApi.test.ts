import { toolbarApi } from '~/toolbar/toolbarApi'
import { toolbarFetch } from '~/toolbar/toolbarFetch'
import { captureToolbarException } from '~/toolbar/toolbarPosthogJS'

jest.mock('~/toolbar/toolbarFetch', () => ({ toolbarFetch: jest.fn() }))
jest.mock('~/toolbar/toolbarPosthogJS', () => ({ captureToolbarException: jest.fn() }))

const mockToolbarFetch = toolbarFetch as jest.Mock
const mockCaptureException = captureToolbarException as jest.Mock

describe('toolbarApi request error reporting', () => {
    beforeEach(() => {
        jest.clearAllMocks()
    })

    it('does not report benign network-level failures to error tracking', async () => {
        // A request that never reaches the server (offline, nav-away, ad blocker) — the noise this guards against.
        mockToolbarFetch.mockRejectedValue(new TypeError('Failed to fetch'))

        const result = await toolbarApi.get('/api/projects/@current/product_tours/', { context: 'load_product_tours' })

        expect(result.ok).toBe(false)
        if (result.ok) {
            throw new Error('expected a failure result')
        }
        expect(result.error.isNetworkError).toBe(true)
        expect(mockCaptureException).not.toHaveBeenCalled()
    })

    it('reports 5xx server errors to error tracking', async () => {
        mockToolbarFetch.mockResolvedValue(new Response(JSON.stringify({ detail: 'boom' }), { status: 500 }))

        const result = await toolbarApi.get('/api/projects/@current/product_tours/', { context: 'load_product_tours' })

        expect(result.ok).toBe(false)
        expect(mockCaptureException).toHaveBeenCalledTimes(1)
        expect(mockCaptureException).toHaveBeenCalledWith(expect.anything(), 'load_product_tours', { status: 500 })
    })

    it('reports malformed JSON responses to error tracking', async () => {
        mockToolbarFetch.mockResolvedValue(new Response('not json', { status: 200 }))

        const result = await toolbarApi.get('/api/projects/@current/product_tours/', { context: 'load_product_tours' })

        expect(result.ok).toBe(false)
        expect(mockCaptureException).toHaveBeenCalledTimes(1)
        expect(mockCaptureException).toHaveBeenCalledWith(expect.anything(), 'load_product_tours', {
            reason: 'invalid_json',
            status: 200,
        })
    })

    it('does not report expected 4xx client errors to error tracking', async () => {
        mockToolbarFetch.mockResolvedValue(new Response(JSON.stringify({ detail: 'nope' }), { status: 400 }))

        const result = await toolbarApi.get('/api/projects/@current/product_tours/', { context: 'load_product_tours' })

        expect(result.ok).toBe(false)
        expect(mockCaptureException).not.toHaveBeenCalled()
    })
})
