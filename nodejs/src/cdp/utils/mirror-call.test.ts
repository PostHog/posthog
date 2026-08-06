import { logger } from '~/common/utils/logger'

import { mirrorCall, mirrorCompare } from './mirror-call'

jest.mock('~/common/utils/logger', () => ({ logger: { warn: jest.fn() } }))

describe('mirrorCall', () => {
    it('resolves when the call resolves in time', async () => {
        const call = jest.fn().mockResolvedValue('ok')
        await mirrorCall('test.op', call, 50)
        expect(call).toHaveBeenCalledTimes(1)
    })

    it('catches and logs errors instead of throwing', async () => {
        const call = jest.fn().mockRejectedValue(new Error('boom'))
        await expect(mirrorCall('test.op', call, 50)).resolves.toBeUndefined()
    })

    it('stops awaiting after timeoutMs and never throws', async () => {
        const call = jest.fn().mockImplementation(() => new Promise(() => {})) // never settles
        const start = Date.now()
        await mirrorCall('test.op', call, 20)
        const elapsed = Date.now() - start
        expect(elapsed).toBeLessThan(200)
    })

    it('returns the primary result when mirror results match', async () => {
        await expect(
            mirrorCompare(
                'test.compare',
                () => Promise.resolve({ state: 'healthy' }),
                () => Promise.resolve({ state: 'healthy' })
            )
        ).resolves.toEqual({ state: 'healthy' })
        expect(logger.warn).not.toHaveBeenCalledWith('🪞', '[mirror:test.compare] result mismatch')
    })

    it('reports a mismatch without changing the primary result', async () => {
        await expect(
            mirrorCompare(
                'test.compare',
                () => Promise.resolve({ state: 'healthy' }),
                () => Promise.resolve({ state: 'degraded' })
            )
        ).resolves.toEqual({ state: 'healthy' })
        expect(logger.warn).toHaveBeenCalledWith('🪞', '[mirror:test.compare] result mismatch')
    })

    it('returns the primary result when the comparator throws on an unexpected mirror shape', async () => {
        await expect(
            mirrorCompare<{ isRateLimited: boolean }[]>(
                'test.compare',
                () => Promise.resolve([{ isRateLimited: false }]),
                () => Promise.resolve(undefined as any),
                (primary, mirror) => primary.every((entry, i) => entry.isRateLimited === mirror[i].isRateLimited)
            )
        ).resolves.toEqual([{ isRateLimited: false }])
    })

    it('returns the primary result when the mirror fails', async () => {
        await expect(
            mirrorCompare(
                'test.compare',
                () => Promise.resolve('primary'),
                () => Promise.reject(new Error('boom'))
            )
        ).resolves.toBe('primary')
    })
})
