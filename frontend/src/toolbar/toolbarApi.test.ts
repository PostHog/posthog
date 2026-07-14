jest.mock('lib/lemon-ui/LemonToast/LemonToast', () => ({
    lemonToast: { success: jest.fn(), error: jest.fn() },
}))

// The toolbar logger mirrors intentional error/auth paths to the console (its job on
// customer pages); these tests exercise those paths on purpose, so stub the boundary.
jest.mock('~/toolbar/toolbarLogger', () => ({
    toolbarLogger: { debug: jest.fn(), info: jest.fn(), warn: jest.fn(), error: jest.fn() },
}))

jest.mock('~/toolbar/toolbarPosthogJS', () => ({
    captureToolbarException: jest.fn(),
}))

jest.mock('~/toolbar/toolbarFetch', () => ({
    toolbarFetch: jest.fn(),
}))

import { toolbarApi } from '~/toolbar/toolbarApi'
import { toolbarFetch } from '~/toolbar/toolbarFetch'
import { captureToolbarException } from '~/toolbar/toolbarPosthogJS'

const mockToolbarFetch = toolbarFetch as jest.Mock
const mockCapture = captureToolbarException as jest.Mock

describe('toolbarApi', () => {
    beforeEach(() => {
        jest.clearAllMocks()
    })

    it.each([
        {
            name: 'transient network failure (fetch rejects with TypeError: Failed to fetch)',
            setupMock: () => mockToolbarFetch.mockRejectedValueOnce(new TypeError('Failed to fetch')),
            expectCapture: false,
        },
        {
            name: '5xx server error',
            setupMock: () => mockToolbarFetch.mockResolvedValueOnce({ ok: false, status: 500, json: async () => ({}) }),
            expectCapture: true,
        },
        {
            name: 'malformed JSON on a 200 response',
            setupMock: () =>
                mockToolbarFetch.mockResolvedValueOnce({
                    ok: true,
                    status: 200,
                    json: async () => {
                        throw new SyntaxError('Unexpected token')
                    },
                }),
            expectCapture: true,
        },
    ])('reports only genuinely-unexpected failures as exceptions: $name', async ({ setupMock, expectCapture }) => {
        setupMock()

        const result = await toolbarApi.get('/api/projects/@current/product_tours/', { context: 'load_product_tours' })

        expect(result.ok).toBe(false)
        if (expectCapture) {
            expect(mockCapture).toHaveBeenCalledTimes(1)
        } else {
            expect(mockCapture).not.toHaveBeenCalled()
        }
    })

    it('does not capture a network failure even when a client 4xx would also be silent', async () => {
        // Guards that the network branch is unconditional — not gated on captureOnError like 5xx/JSON.
        mockToolbarFetch.mockRejectedValueOnce(new TypeError('Failed to fetch'))

        const result = await toolbarApi.get('/api/projects/@current/web_experiments/', {
            context: 'load_experiments',
            captureOnError: true,
        })

        expect(result.ok).toBe(false)
        if (!result.ok) {
            expect(result.error.isNetworkError).toBe(true)
        }
        expect(mockCapture).not.toHaveBeenCalled()
    })
})
