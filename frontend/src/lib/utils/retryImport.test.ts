import { isChunkLoadError } from './isChunkLoadError'
import { requireBootExport, retryBootImport, retryImport } from './retryImport'

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

    it.each([
        ['a bare minified identifier', 'g is not a function'],
        ['a property access on a minified identifier', 'i.bootApp is not a function'],
        ['a bare minified identifier with WebKit diagnostics', "g is not a function. (In 'g()', 'g' is undefined)"],
        [
            'a property access with WebKit diagnostics',
            "i.bootApp is not a function. (In 'i.bootApp()', 'i.bootApp' is undefined)",
        ],
    ])('marks a boot module-evaluation TypeError from %s without retrying', async (_label, message) => {
        const error = new TypeError(message)
        const factory = jest.fn().mockRejectedValue(error)

        await expect(retryBootImport(factory)).rejects.toBe(error)
        expect(factory).toHaveBeenCalledTimes(1)
        expect(isChunkLoadError(error)).toBe(true)
    })

    it('leaves a readable name unclassified when WebKit adds its diagnostics', async () => {
        const error = new TypeError("bootApp is not a function. (In 'bootApp()', 'bootApp' is undefined)")
        const factory = jest.fn().mockRejectedValue(error)

        await expect(retryBootImport(factory)).rejects.toBe(error)
        expect(isChunkLoadError(error)).toBe(false)
    })

    it('returns the export a boot module carries', () => {
        const bootApp = jest.fn()

        expect(requireBootExport({ bootApp }, 'bootApp')).toBe(bootApp)
    })

    it('classifies a boot module without its export as a chunk-load failure', () => {
        let thrown: unknown
        try {
            requireBootExport({ bootApp: undefined }, 'bootApp')
        } catch (error) {
            thrown = error
        }

        expect(thrown).toBeInstanceOf(TypeError)
        expect(isChunkLoadError(thrown)).toBe(true)
    })

    it('rethrows a non-chunk error immediately without retrying', async () => {
        const factory = jest.fn().mockRejectedValue(new TypeError('undefined is not a function'))

        await expect(retryImport(factory)).rejects.toThrow('undefined is not a function')
        expect(factory).toHaveBeenCalledTimes(1)
    })
})
