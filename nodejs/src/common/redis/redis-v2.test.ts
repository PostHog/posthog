import { createPool } from 'generic-pool'

import * as posthog from '~/common/utils/posthog'

import { createRedisV2PoolFromConfig } from './redis-v2'

jest.mock('generic-pool', () => ({ createPool: jest.fn() }))
jest.mock('~/common/utils/db/redis', () => ({ createRedisFromConfig: jest.fn() }))

describe('createRedisV2PoolFromConfig()', () => {
    let acquire: jest.Mock
    let release: jest.Mock
    let captureExceptionSpy: jest.SpyInstance

    beforeEach(() => {
        acquire = jest.fn()
        release = jest.fn().mockResolvedValue(undefined)
        jest.mocked(createPool).mockReturnValue({ acquire, release } as any)
        captureExceptionSpy = jest.spyOn(posthog, 'captureException').mockImplementation(() => {})
        jest.useFakeTimers()
    })

    afterEach(() => {
        jest.useRealTimers()
        jest.restoreAllMocks()
    })

    const buildRedis = () => createRedisV2PoolFromConfig({ connection: {}, poolMinSize: 1, poolMaxSize: 1 } as any)

    // The guard starts before acquisition. When acquisition rejects, an uncleared timer later
    // reports a timeout for a call that never ran, which is a false error tracking signal.
    it('clears the timeout guard when acquiring a client rejects', async () => {
        acquire.mockRejectedValue(new Error('pool exhausted'))
        const redis = buildRedis()

        await expect(redis.useClient({ name: 'ping', timeout: 100 }, () => Promise.resolve('unused'))).rejects.toThrow(
            'pool exhausted'
        )
        jest.runOnlyPendingTimers()

        expect(captureExceptionSpy).not.toHaveBeenCalled()
        expect(release).not.toHaveBeenCalled()
    })

    it('releases the client and clears the guard when the callback succeeds', async () => {
        const client = {}
        acquire.mockResolvedValue(client)
        const redis = buildRedis()

        await expect(redis.useClient({ name: 'ping', timeout: 100 }, () => Promise.resolve('value'))).resolves.toBe(
            'value'
        )
        jest.runOnlyPendingTimers()

        expect(captureExceptionSpy).not.toHaveBeenCalled()
        expect(release).toHaveBeenCalledWith(client)
    })
})
