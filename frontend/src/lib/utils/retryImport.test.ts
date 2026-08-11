import { isChunkLoadError } from './isChunkLoadError'
import { retryBootImport, retryImport } from './retryImport'

describe('retryImport', () => {
    beforeEach(() => {
        jest.useFakeTimers()
    })

    afterEach(() => {
        jest.useRealTimers()
    })

    const chunkError = (): Error => new Error('Failed to fetch dynamically imported module: /x.js')

    it('resolves on the first attempt without retrying', async () => {
        const factory = jest.fn().mockResolvedValue('module')

        await expect(retryImport(factory)).resolves.toBe('module')
        expect(factory).toHaveBeenCalledTimes(1)
    })

    it('resolves a factory that returns a non-promise value', async () => {
        const factory = jest.fn().mockReturnValue('module')

        await expect(retryImport(factory)).resolves.toBe('module')
        expect(factory).toHaveBeenCalledTimes(1)
    })

    it('retries a transient chunk error and resolves', async () => {
        const factory = jest.fn().mockRejectedValueOnce(chunkError()).mockResolvedValue('module')

        const promise = retryImport(factory)
        await jest.runAllTimersAsync()

        await expect(promise).resolves.toBe('module')
        expect(factory).toHaveBeenCalledTimes(2)
    })

    it('exhausts retries on a persistent chunk error and rejects', async () => {
        const factory = jest.fn().mockRejectedValue(chunkError())

        const promise = retryImport(factory)
        void promise.catch(() => {}) // avoid an unhandled rejection while the backoff timers drain
        await jest.runAllTimersAsync()

        await expect(promise).rejects.toThrow('Failed to fetch dynamically imported module')
        expect(factory).toHaveBeenCalledTimes(3)
    })

    it('marks a minified boot module-evaluation TypeError without retrying', async () => {
        const error = new TypeError('g is not a function')
        const factory = jest.fn().mockRejectedValue(error)

        await expect(retryBootImport(factory)).rejects.toBe(error)
        expect(factory).toHaveBeenCalledTimes(1)
        expect(isChunkLoadError(error)).toBe(true)
    })

    it('rethrows a non-chunk error immediately without retrying', async () => {
        const factory = jest.fn().mockRejectedValue(new TypeError('undefined is not a function'))

        await expect(retryImport(factory)).rejects.toThrow('undefined is not a function')
        expect(factory).toHaveBeenCalledTimes(1)
    })

    it('retries a chunk that parsed as HTML and marks it for the boundary', async () => {
        const parseError = new SyntaxError('Invalid or unexpected token')
        const factory = jest.fn().mockRejectedValueOnce(parseError).mockResolvedValue('module')

        const promise = retryImport(factory)
        await jest.runAllTimersAsync()

        await expect(promise).resolves.toBe('module')
        expect(factory).toHaveBeenCalledTimes(2)
        // The boundary reloads once on the same error object if the retry never succeeds.
        expect(isChunkLoadError(parseError)).toBe(true)
    })

    it('rethrows a genuine SyntaxError without retrying', async () => {
        const factory = jest.fn().mockRejectedValue(new SyntaxError('Unexpected end of JSON input'))

        await expect(retryImport(factory)).rejects.toThrow('Unexpected end of JSON input')
        expect(factory).toHaveBeenCalledTimes(1)
    })

    it('retries Chromium\'s bare "Failed to fetch" and marks it for the boundary', async () => {
        const fetchError = new TypeError('Failed to fetch')
        const factory = jest.fn().mockRejectedValueOnce(fetchError).mockResolvedValue('module')

        const promise = retryImport(factory)
        await jest.runAllTimersAsync()

        await expect(promise).resolves.toBe('module')
        expect(factory).toHaveBeenCalledTimes(2)
        // The boundary reloads once on the same error object if the retry never succeeds.
        expect(isChunkLoadError(fetchError)).toBe(true)
    })
})
