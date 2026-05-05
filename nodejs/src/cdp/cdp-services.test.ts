import { RedisV2 } from '~/common/redis/redis-v2'

import { createCdpReaderRedisPool } from './cdp-services'

jest.mock('~/common/redis/redis-v2', () => ({
    createRedisV2PoolFromConfig: jest.fn(() => 'mocked-reader-pool'),
}))

const { createRedisV2PoolFromConfig } = require('~/common/redis/redis-v2') as {
    createRedisV2PoolFromConfig: jest.Mock
}

const mockWriterPool = { useClient: jest.fn(), usePipeline: jest.fn() } as unknown as RedisV2

const baseConfig = {
    CDP_REDIS_HOST: 'cdp-writer.internal',
    CDP_REDIS_PORT: 6379,
    CDP_REDIS_PASSWORD: 'secret',
    CDP_REDIS_READER_HOST: '',
    CDP_REDIS_READER_PORT: 6379,
    REDIS_URL: 'redis://:password@fallback-host:6379',
    REDIS_POOL_MIN_SIZE: 1,
    REDIS_POOL_MAX_SIZE: 4,
}

describe('createCdpReaderRedisPool', () => {
    beforeEach(() => {
        jest.clearAllMocks()
    })

    it('creates a dedicated reader pool when CDP_REDIS_READER_HOST is set', () => {
        const config = { ...baseConfig, CDP_REDIS_READER_HOST: 'cdp-reader.internal', CDP_REDIS_READER_PORT: 6380 }

        const result = createCdpReaderRedisPool(config, mockWriterPool, 'test-redis')

        expect(result).toBe('mocked-reader-pool')
        expect(createRedisV2PoolFromConfig).toHaveBeenCalledWith({
            connection: {
                url: 'cdp-reader.internal',
                options: { port: 6380, password: 'secret' },
                name: 'test-redis-reader',
            },
            poolMinSize: 1,
            poolMaxSize: 4,
        })
    })

    it('falls back to writer pool when CDP_REDIS_READER_HOST is not set', () => {
        const config = { ...baseConfig, CDP_REDIS_READER_HOST: '' }

        const result = createCdpReaderRedisPool(config, mockWriterPool, 'test-redis')

        expect(result).toBe(mockWriterPool)
        expect(createRedisV2PoolFromConfig).not.toHaveBeenCalled()
    })

    it('does not leak credentials from REDIS_URL in fallback log', () => {
        const logSpy = jest.spyOn(require('~/utils/logger').logger, 'info')
        const config = {
            ...baseConfig,
            CDP_REDIS_HOST: '',
            CDP_REDIS_READER_HOST: '',
            REDIS_URL: 'redis://:supersecret@prod-redis.internal:6379',
        }

        createCdpReaderRedisPool(config, mockWriterPool, 'test-redis')

        const logMessage = logSpy.mock.calls[0]?.[1] as string
        expect(logMessage).not.toContain('supersecret')
        expect(logMessage).toContain('prod-redis.internal')
    })
})
