import { mirrorCall, mirrorCallWithPrimary } from './mirror-call'

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

    it('returns the primary result after running the mirror', async () => {
        const mirror = jest.fn().mockResolvedValue('shadow')
        await expect(mirrorCallWithPrimary('test.pair', () => Promise.resolve('primary'), mirror)).resolves.toBe(
            'primary'
        )
        expect(mirror).toHaveBeenCalledTimes(1)
    })

    it('returns the primary result when the mirror fails', async () => {
        await expect(
            mirrorCallWithPrimary(
                'test.pair',
                () => Promise.resolve('primary'),
                () => Promise.reject(new Error('boom'))
            )
        ).resolves.toBe('primary')
    })
})
