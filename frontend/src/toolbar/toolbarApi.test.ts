import { toolbarApi } from '~/toolbar/toolbarApi'
import { toolbarFetch } from '~/toolbar/toolbarFetch'
import { captureToolbarException } from '~/toolbar/toolbarPosthogJS'

jest.mock('~/toolbar/toolbarFetch')
jest.mock('~/toolbar/toolbarPosthogJS', () => ({
    ...jest.requireActual('~/toolbar/toolbarPosthogJS'),
    captureToolbarException: jest.fn(),
}))

const mockFetch = toolbarFetch as jest.MockedFunction<typeof toolbarFetch>
const mockCapture = captureToolbarException as jest.MockedFunction<typeof captureToolbarException>

describe('toolbarApi network failure reporting', () => {
    beforeEach(() => {
        jest.clearAllMocks()
    })

    it('does not report a benign "Failed to fetch" network error as an exception', async () => {
        mockFetch.mockRejectedValueOnce(new TypeError('Failed to fetch'))

        const result = await toolbarApi.webVitals.get({ pathname: '/' }, { context: 'load_web_vitals' })

        expect(result.ok).toBe(false)
        expect(result.ok === false && result.error.isNetworkError).toBe(true)
        expect(mockCapture).not.toHaveBeenCalled()
    })

    it('does not report an aborted/timed-out request as an exception', async () => {
        mockFetch.mockRejectedValueOnce(new DOMException('The operation was aborted.', 'AbortError'))

        const result = await toolbarApi.webVitals.get({ pathname: '/' }, { context: 'load_web_vitals' })

        expect(result.ok).toBe(false)
        expect(mockCapture).not.toHaveBeenCalled()
    })

    it('still reports a genuinely unexpected failure (e.g. a thrown non-network error)', async () => {
        mockFetch.mockRejectedValueOnce(new Error('window.fetch was replaced and threw'))

        const result = await toolbarApi.webVitals.get({ pathname: '/' }, { context: 'load_web_vitals' })

        expect(result.ok).toBe(false)
        expect(mockCapture).toHaveBeenCalledTimes(1)
    })

    it('still reports a 5xx server error as an exception', async () => {
        mockFetch.mockResolvedValueOnce({
            ok: false,
            status: 500,
            json: () => Promise.resolve({ detail: 'boom' }),
        } as Response)

        const result = await toolbarApi.webVitals.get({ pathname: '/' }, { context: 'load_web_vitals' })

        expect(result.ok).toBe(false)
        expect(mockCapture).toHaveBeenCalledTimes(1)
    })
})
