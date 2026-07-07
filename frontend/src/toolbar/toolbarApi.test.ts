// Spy on the exception-capture boundary so we can assert what does and doesn't get reported.
jest.mock('~/toolbar/toolbarPosthogJS', () => ({
    ...jest.requireActual('~/toolbar/toolbarPosthogJS'),
    captureToolbarException: jest.fn(),
}))
// The logger is just a sink here — silence it so failing-request cases don't spam test output.
jest.mock('~/toolbar/toolbarLogger', () => ({
    toolbarLogger: { error: jest.fn(), warn: jest.fn(), info: jest.fn(), debug: jest.fn() },
}))
jest.mock('~/toolbar/toolbarFetch', () => ({
    toolbarFetch: jest.fn(),
}))

import { toolbarApi } from '~/toolbar/toolbarApi'
import { toolbarFetch } from '~/toolbar/toolbarFetch'
import { captureToolbarException } from '~/toolbar/toolbarPosthogJS'

const mockToolbarFetch = toolbarFetch as jest.Mock

describe('toolbarApi request exception capture', () => {
    beforeEach(() => {
        jest.clearAllMocks()
    })

    it.each([
        {
            name: 'network-level failure (fetch rejects) is environmental, not reported',
            setup: () => mockToolbarFetch.mockRejectedValueOnce(new TypeError('Failed to fetch')),
            expectedCaptureCalls: 0,
        },
        {
            name: 'auth error (401) is expected, not reported',
            setup: () => mockToolbarFetch.mockResolvedValueOnce({ ok: false, status: 401, json: async () => ({}) }),
            expectedCaptureCalls: 0,
        },
        {
            name: 'client error (400) is expected, not reported',
            setup: () => mockToolbarFetch.mockResolvedValueOnce({ ok: false, status: 400, json: async () => ({}) }),
            expectedCaptureCalls: 0,
        },
        {
            name: 'server error (500) is unexpected, reported',
            setup: () => mockToolbarFetch.mockResolvedValueOnce({ ok: false, status: 500, json: async () => ({}) }),
            expectedCaptureCalls: 1,
        },
        {
            name: 'malformed JSON on a 200 is unexpected, reported',
            setup: () =>
                mockToolbarFetch.mockResolvedValueOnce({
                    ok: true,
                    status: 200,
                    json: async () => {
                        throw new SyntaxError('Unexpected token')
                    },
                }),
            expectedCaptureCalls: 1,
        },
    ])('$name', async ({ setup, expectedCaptureCalls }) => {
        setup()

        const result = await toolbarApi.get('/api/anything/', { context: 'load_product_tours' })

        expect(result.ok).toBe(false)
        expect(captureToolbarException).toHaveBeenCalledTimes(expectedCaptureCalls)
    })
})
