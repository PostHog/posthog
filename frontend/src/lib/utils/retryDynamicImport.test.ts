import { retryDynamicImport } from './retryDynamicImport'

describe('retryDynamicImport', () => {
    beforeEach(() => {
        jest.useFakeTimers()
    })

    afterEach(() => {
        jest.useRealTimers()
    })

    it('returns the module on first success without delay', async () => {
        const importer = jest.fn().mockResolvedValue({ default: 'scene' })

        await expect(retryDynamicImport(importer)).resolves.toEqual({ default: 'scene' })
        expect(importer).toHaveBeenCalledTimes(1)
    })

    it('retries a transient fetch failure and succeeds', async () => {
        const importer = jest
            .fn()
            .mockRejectedValueOnce(new TypeError('Failed to fetch'))
            .mockResolvedValue({ default: 'scene' })

        const promise = retryDynamicImport(importer, { baseDelayMs: 10 })
        await jest.runAllTimersAsync()

        await expect(promise).resolves.toEqual({ default: 'scene' })
        expect(importer).toHaveBeenCalledTimes(2)
    })

    it('gives up after exhausting retries and throws the last error', async () => {
        const error = new TypeError('Failed to fetch dynamically imported module: /static/chunk.js')
        const importer = jest.fn().mockRejectedValue(error)

        const promise = retryDynamicImport(importer, { retries: 2, baseDelayMs: 10 })
        // Attach a rejection handler before advancing timers so the rejection is never unhandled.
        const assertion = expect(promise).rejects.toBe(error)
        await jest.runAllTimersAsync()
        await assertion

        expect(importer).toHaveBeenCalledTimes(3)
    })

    it('does not retry a non-network module error', async () => {
        const error = new Error('Unexpected token in module')
        const importer = jest.fn().mockRejectedValue(error)

        await expect(retryDynamicImport(importer)).rejects.toBe(error)
        expect(importer).toHaveBeenCalledTimes(1)
    })
})
