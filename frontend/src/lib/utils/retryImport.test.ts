import { retryImport } from './retryImport'

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

    it('rethrows a non-chunk error immediately without retrying', async () => {
        const factory = jest.fn().mockRejectedValue(new TypeError('undefined is not a function'))

        await expect(retryImport(factory)).rejects.toThrow('undefined is not a function')
        expect(factory).toHaveBeenCalledTimes(1)
    })
})
