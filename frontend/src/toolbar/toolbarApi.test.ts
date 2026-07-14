import { toolbarApi } from '~/toolbar/toolbarApi'
import { toolbarFetch } from '~/toolbar/toolbarFetch'
import { captureToolbarException } from '~/toolbar/toolbarPosthogJS'

jest.mock('~/toolbar/toolbarFetch', () => ({ toolbarFetch: jest.fn() }))
// Keep the real posthog-js instance and the real isBenignNetworkError helper, but spy
// on the capture helper so we can assert what does and doesn't reach error tracking.
jest.mock('~/toolbar/toolbarPosthogJS', () => ({
    ...jest.requireActual('~/toolbar/toolbarPosthogJS'),
    captureToolbarException: jest.fn(),
}))

describe('toolbarApi', () => {
    beforeEach(() => {
        jest.clearAllMocks()
    })

    // Benign `Failed to fetch` network/CORS failures (a TypeError) fire constantly on
    // third-party customer pages and must not be reported as exceptions, but a genuinely
    // unexpected throw from the transport still has to reach error tracking.
    it.each([
        {
            name: 'benign network/CORS failure (TypeError) is not captured',
            thrown: new TypeError('Failed to fetch'),
            expectCapture: false,
        },
        {
            name: 'unexpected non-network throw is captured',
            thrown: new Error('boom'),
            expectCapture: true,
        },
    ])('network failure reporting: $name', async ({ thrown, expectCapture }) => {
        ;(toolbarFetch as jest.Mock).mockRejectedValueOnce(thrown)

        const result = await toolbarApi.webVitals.get({ pathname: '/' }, { context: 'load_web_vitals' })

        expect(result.ok).toBe(false)
        if (!result.ok) {
            expect(result.error.isNetworkError).toBe(true)
        }
        if (expectCapture) {
            expect(captureToolbarException).toHaveBeenCalledWith(thrown, 'load_web_vitals', { reason: 'network' })
        } else {
            expect(captureToolbarException).not.toHaveBeenCalled()
        }
    })
})
