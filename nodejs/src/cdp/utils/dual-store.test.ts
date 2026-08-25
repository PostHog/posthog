import { logger } from '~/common/utils/logger'

import { configureValkeyReads, dualRead, dualWrite, parseValkeyReadFeatures, readSourceFor } from './dual-store'

jest.mock('~/common/utils/logger', () => ({ logger: { warn: jest.fn(), info: jest.fn() } }))

describe('dual-store', () => {
    beforeEach(() => {
        jest.clearAllMocks()
        configureValkeyReads('')
    })

    describe('parseValkeyReadFeatures', () => {
        it('throws on an unknown feature name rather than silently leaving reads on redis', () => {
            expect(() => parseValkeyReadFeatures('hog-masker,hog-waatcher')).toThrow(
                /unknown feature\(s\): hog-waatcher/
            )
        })

        it('selects every feature for *', () => {
            expect(parseValkeyReadFeatures('*').size).toBeGreaterThan(1)
        })

        it('reads only the named features from valkey', () => {
            configureValkeyReads(' hog-masker , hog-flow-duplicate-observer ')
            expect(readSourceFor('hog-masker.filterByMasking')).toBe('valkey')
            expect(readSourceFor('hog-flow-duplicate-observer.observe')).toBe('valkey')
            expect(readSourceFor('hog-watcher.getEffectiveStates')).toBe('redis')
        })
    })

    describe('dualRead', () => {
        it.each([
            ['', 'redis-value'],
            ['hog-masker', 'valkey-value'],
        ])('with CDP_VALKEY_READ_FEATURES=%p returns %p', async (features, expected) => {
            configureValkeyReads(features)
            await expect(
                dualRead(
                    'hog-masker.filterByMasking',
                    () => Promise.resolve('redis-value'),
                    () => Promise.resolve('valkey-value')
                )
            ).resolves.toBe(expected)
        })

        it.each([
            ['', 'valkey'],
            ['hog-masker', 'redis'],
        ])('with CDP_VALKEY_READ_FEATURES=%p a failing %s read never reaches the caller', async (features, failing) => {
            configureValkeyReads(features)
            const boom = () => Promise.reject(new Error('boom'))
            const ok = () => Promise.resolve('ok')
            await expect(
                dualRead(
                    'hog-masker.filterByMasking',
                    failing === 'redis' ? boom : ok,
                    failing === 'valkey' ? boom : ok
                )
            ).resolves.toBe('ok')
        })

        it('stops awaiting the non-read store after timeoutMs', async () => {
            const start = Date.now()
            await expect(
                dualRead(
                    'hog-masker.filterByMasking',
                    () => Promise.resolve('redis-value'),
                    () => new Promise(() => {}), // never settles
                    undefined,
                    20
                )
            ).resolves.toBe('redis-value')
            expect(Date.now() - start).toBeLessThan(200)
        })

        it('logs a mismatch once without changing the returned result', async () => {
            await expect(
                dualRead(
                    'hog-watcher.getPersistedState',
                    () => Promise.resolve({ state: 'healthy' }),
                    () => Promise.resolve({ state: 'degraded' })
                )
            ).resolves.toEqual({ state: 'healthy' })
            expect(logger.warn).toHaveBeenCalledWith('🪞', '[mirror:hog-watcher.getPersistedState] result mismatch')
        })

        it('returns the read-store result when the comparator throws on an unexpected shape', async () => {
            await expect(
                dualRead<{ isRateLimited: boolean }[]>(
                    'hog-function-rate-limiter.rateLimitGrouped',
                    () => Promise.resolve([{ isRateLimited: false }]),
                    () => Promise.resolve(undefined as any),
                    (primary, secondary) =>
                        primary.every((entry, i) => entry.isRateLimited === secondary[i].isRateLimited)
                )
            ).resolves.toEqual([{ isRateLimited: false }])
        })
    })

    describe('dualWrite', () => {
        it.each([
            ['', 'redis'],
            ['hog-watcher', 'valkey'],
        ])(
            'with CDP_VALKEY_READ_FEATURES=%p only a failing %s write reaches the caller',
            async (features, propagating) => {
                configureValkeyReads(features)
                const boom = () => Promise.reject(new Error('boom'))
                const ok = () => Promise.resolve()

                await expect(
                    dualWrite(
                        'hog-watcher.observeResults',
                        propagating === 'redis' ? boom : ok,
                        propagating === 'valkey' ? boom : ok
                    )
                ).rejects.toThrow('boom')

                await expect(
                    dualWrite(
                        'hog-watcher.observeResults',
                        propagating === 'redis' ? ok : boom,
                        propagating === 'valkey' ? ok : boom
                    )
                ).resolves.toBeUndefined()
            }
        )

        it('writes to both stores', async () => {
            const redis = jest.fn().mockResolvedValue(undefined)
            const valkey = jest.fn().mockResolvedValue(undefined)
            await dualWrite('hog-watcher.observeResults', redis, valkey)
            expect(redis).toHaveBeenCalledTimes(1)
            expect(valkey).toHaveBeenCalledTimes(1)
        })
    })
})
