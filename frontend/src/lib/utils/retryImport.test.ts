import { isChunkLoadError } from './isChunkLoadError'
import { retryImport, retryReloadableImport } from './retryImport'

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

    const minifiedEvaluationErrors: [string, string][] = [
        ['V8 call shape', 'g is not a function'],
        ['Firefox property access', `can't access property "message", _ is undefined`],
    ]

    it.each(minifiedEvaluationErrors)(
        'marks a minified module-evaluation TypeError on a reloadable import without retrying (%s)',
        async (_name, message) => {
            const error = new TypeError(message)
            const factory = jest.fn().mockRejectedValue(error)

            await expect(retryReloadableImport(factory)).rejects.toBe(error)
            expect(factory).toHaveBeenCalledTimes(1)
            expect(isChunkLoadError(error)).toBe(true)
        }
    )

    it.each(minifiedEvaluationErrors)(
        'leaves a minified module-evaluation TypeError unmarked on an ordinary import (%s)',
        async (_name, message) => {
            const error = new TypeError(message)
            const factory = jest.fn().mockRejectedValue(error)

            await expect(retryImport(factory)).rejects.toBe(error)
            expect(factory).toHaveBeenCalledTimes(1)
            expect(isChunkLoadError(error)).toBe(false)
        }
    )

    it.each([
        ['a multi-character subject', 'undefined is not a function'],
        ['a subject-free property access', `Cannot read properties of undefined (reading 'message')`],
    ])('leaves an unrelated TypeError unmarked on a reloadable import (%s)', async (_name, message) => {
        const error = new TypeError(message)
        const factory = jest.fn().mockRejectedValue(error)

        await expect(retryReloadableImport(factory)).rejects.toBe(error)
        expect(factory).toHaveBeenCalledTimes(1)
        expect(isChunkLoadError(error)).toBe(false)
    })

    it('retries a generic network TypeError and marks it as a chunk load error once exhausted', async () => {
        const error = new TypeError('Load failed')
        const factory = jest.fn().mockRejectedValue(error)

        const promise = retryImport(factory)
        void promise.catch(() => {})
        await jest.runAllTimersAsync()

        await expect(promise).rejects.toBe(error)
        expect(factory).toHaveBeenCalledTimes(3)
        expect(isChunkLoadError(error)).toBe(true)
    })
})
