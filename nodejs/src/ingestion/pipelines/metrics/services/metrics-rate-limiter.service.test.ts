import { Message } from 'node-rdkafka'

import { RedisV2 } from '~/common/redis/redis-v2'
import { killGracefully } from '~/common/utils/utils'
import { getDefaultMetricsIngestionConsumerConfig } from '~/ingestion/pipelines/metrics/config'
import { MetricsIngestionMessage } from '~/ingestion/pipelines/metrics/types'

import { MetricsRateLimiterService, metricsRateLimiterRedisErrorsCounter } from './metrics-rate-limiter.service'
import { METRICS_LIMITER_FAIL_OPEN_REDIS_TIMEOUT_MS, createMetricsRateLimiterRedis } from './metrics-redis'

jest.mock('~/common/utils/utils', () => ({ ...jest.requireActual('~/common/utils/utils'), killGracefully: jest.fn() }))

const message = (teamId: number): MetricsIngestionMessage => ({
    token: `token-${teamId}`,
    teamId,
    message: { headers: [] } as unknown as Message,
    bytesUncompressed: 1000,
    bytesUncompressedRecords: 0,
    bytesCompressed: 100,
    recordCount: 1,
})

const createService = (failOpen: boolean, usePipeline: jest.Mock): MetricsRateLimiterService => {
    const config = {
        ...getDefaultMetricsIngestionConsumerConfig(),
        METRICS_LIMITER_ENABLED_TEAMS: '*',
        METRICS_LIMITER_FAIL_OPEN: failOpen,
    }
    return new MetricsRateLimiterService(config, { usePipeline } as unknown as RedisV2)
}

const errorCount = async (): Promise<number> => (await metricsRateLimiterRedisErrorsCounter.get()).values[0]?.value ?? 0

describe('MetricsRateLimiterService when Redis is unavailable', () => {
    const messages = [message(1), message(2)]

    beforeEach(() => {
        metricsRateLimiterRedisErrorsCounter.reset()
    })

    it.each([
        ['returns no result', jest.fn().mockResolvedValue(null)],
        ['throws', jest.fn().mockRejectedValue(new Error('pool acquire timeout'))],
    ])('fails closed by default when Redis %s', async (_, usePipeline) => {
        const service = createService(false, usePipeline)

        await expect(service.filterMessages(messages)).rejects.toThrow()
        expect(await errorCount()).toBe(0)
    })

    it.each([
        ['returns no result', jest.fn().mockResolvedValue(null)],
        ['throws', jest.fn().mockRejectedValue(new Error('pool acquire timeout'))],
        [
            'returns command errors',
            jest.fn().mockResolvedValue([
                [new Error('Connection is closed'), null],
                [new Error('Connection is closed'), null],
            ]),
        ],
    ])('allows every message and counts the error when fail-open is on and Redis %s', async (_, usePipeline) => {
        const service = createService(true, usePipeline)

        const result = await service.filterMessages(messages)

        expect(result.allowed).toEqual(messages)
        expect(result.dropped).toEqual([])
        expect(await errorCount()).toBe(1)
    })

    it('allows every message when fail-open is on and Redis never answers', async () => {
        jest.useFakeTimers()
        try {
            const service = createService(true, jest.fn().mockReturnValue(new Promise(() => {})))

            const pending = service.filterMessages(messages)
            await jest.advanceTimersByTimeAsync(METRICS_LIMITER_FAIL_OPEN_REDIS_TIMEOUT_MS)

            expect((await pending).allowed).toEqual(messages)
            expect(await errorCount()).toBe(1)
        } finally {
            jest.useRealTimers()
        }
    })

    it('allows every message and keeps the process up when fail-open is on and Redis is down', async () => {
        const config = {
            ...getDefaultMetricsIngestionConsumerConfig(),
            METRICS_LIMITER_ENABLED_TEAMS: '*',
            METRICS_LIMITER_FAIL_OPEN: true,
            METRICS_REDIS_HOST: '',
            // Nothing listens on port 1, so every connection attempt fails.
            // nosemgrep: trailofbits.generic.redis-unencrypted-transport.redis-unencrypted-transport
            REDIS_URL: 'redis://127.0.0.1:1',
        }
        const service = new MetricsRateLimiterService(config, createMetricsRateLimiterRedis(config))

        const result = await service.filterMessages(messages)

        expect(result.allowed).toEqual(messages)
        expect(killGracefully).not.toHaveBeenCalled()
    }, 15_000)
})
