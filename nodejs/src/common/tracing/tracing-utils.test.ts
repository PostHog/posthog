jest.mock('~/common/utils/posthog', () => ({
    ...jest.requireActual('~/common/utils/posthog'),
    captureException: jest.fn(),
}))

describe('instrumentFn', () => {
    let instrumentFn: typeof import('./tracing-utils').instrumentFn
    let captureException: jest.Mock

    beforeEach(() => {
        // Something loaded during test setup caches the real posthog module, so reset the registry
        // and re-require both modules to make sure instrumentFn calls the mocked captureException.
        jest.resetModules()
        captureException = require('~/common/utils/posthog').captureException as jest.Mock
        instrumentFn = require('./tracing-utils').instrumentFn
    })

    const timeoutError = Object.assign(new Error('The operation was aborted due to timeout'), {
        name: 'TimeoutError',
    })

    it('does not report request timeouts as exceptions', async () => {
        await expect(instrumentFn('some.operation', () => Promise.reject(timeoutError))).rejects.toBe(timeoutError)

        expect(captureException).not.toHaveBeenCalled()
    })

    it('reports other exceptions with the instrumentation key so they group per operation', async () => {
        const error = new Error('boom')

        await expect(instrumentFn('some.operation', () => Promise.reject(error))).rejects.toBe(error)

        expect(captureException).toHaveBeenCalledWith(error, { tags: { instrumentation_key: 'some.operation' } })
    })

    it('does not report when sendException is false', async () => {
        const error = new Error('boom')

        await expect(
            instrumentFn({ key: 'some.operation', sendException: false }, () => Promise.reject(error))
        ).rejects.toBe(error)

        expect(captureException).not.toHaveBeenCalled()
    })
})
