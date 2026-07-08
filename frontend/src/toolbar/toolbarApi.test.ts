import { toolbarApi } from '~/toolbar/toolbarApi'
import { toolbarFetch } from '~/toolbar/toolbarFetch'
import { captureToolbarException } from '~/toolbar/toolbarPosthogJS'

jest.mock('~/toolbar/toolbarFetch', () => ({ toolbarFetch: jest.fn() }))
jest.mock('~/toolbar/toolbarPosthogJS', () => ({ captureToolbarException: jest.fn() }))

const mockToolbarFetch = toolbarFetch as jest.Mock
const mockCapture = captureToolbarException as jest.Mock

describe('toolbarApi request', () => {
    beforeEach(() => {
        jest.clearAllMocks()
    })

    it('does not report network-level failures as exceptions', async () => {
        // The toolbar runs inside arbitrary customer pages, so a rejected fetch (offline,
        // CORS, ad blocker, a page that wrapped window.fetch) is expected and environmental.
        mockToolbarFetch.mockRejectedValue(new TypeError('Failed to fetch'))

        const result = await toolbarApi.productTours.list({ context: 'load_product_tours' })

        expect(result.ok).toBe(false)
        expect(result.error?.isNetworkError).toBe(true)
        expect(mockCapture).not.toHaveBeenCalled()
    })

    it('still reports 5xx server errors as exceptions', async () => {
        mockToolbarFetch.mockResolvedValue({
            ok: false,
            status: 500,
            json: () => Promise.resolve({ detail: 'boom' }),
        } as unknown as Response)

        const result = await toolbarApi.productTours.list({ context: 'load_product_tours' })

        expect(result.ok).toBe(false)
        expect(result.error?.isNetworkError).toBe(false)
        expect(mockCapture).toHaveBeenCalledTimes(1)
    })
})
