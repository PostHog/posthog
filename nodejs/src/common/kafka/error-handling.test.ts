import { DependencyUnavailableError } from '../utils/db/error'
import { retryOnDependencyUnavailableError } from './error-handling'

describe('retryOnDependencyUnavailableError', () => {
    const dependencyError = (): DependencyUnavailableError =>
        new DependencyUnavailableError('down', 'Postgres', new Error('down'))

    it('returns the result once a retry succeeds', async () => {
        const fn = jest.fn().mockRejectedValueOnce(dependencyError()).mockResolvedValue('ok')

        await expect(retryOnDependencyUnavailableError(fn, { retryCount: 3, initialRetryDelayMs: 1 })).resolves.toBe(
            'ok'
        )
        expect(fn).toHaveBeenCalledTimes(2)
    })

    it('rethrows the dependency error after retryCount attempts', async () => {
        const fn = jest.fn().mockRejectedValue(dependencyError())

        // Guards the limit against a hardcoded attempt count: a retryCount below the hardcoded
        // value used to fall out of the loop with "Should not get here".
        await expect(
            retryOnDependencyUnavailableError(fn, { retryCount: 2, initialRetryDelayMs: 1 })
        ).rejects.toBeInstanceOf(DependencyUnavailableError)
        expect(fn).toHaveBeenCalledTimes(2)
    })

    it('does not retry other errors', async () => {
        const fn = jest.fn().mockRejectedValue(new Error('bad payload'))

        await expect(retryOnDependencyUnavailableError(fn, { retryCount: 3, initialRetryDelayMs: 1 })).rejects.toThrow(
            'bad payload'
        )
        expect(fn).toHaveBeenCalledTimes(1)
    })
})
