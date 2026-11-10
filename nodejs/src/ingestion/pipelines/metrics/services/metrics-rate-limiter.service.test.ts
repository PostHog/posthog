import { Message } from 'node-rdkafka'

import { RedisV2 } from '~/common/redis/redis-v2'
import { getDefaultMetricsIngestionConsumerConfig } from '~/ingestion/pipelines/metrics/config'
import { MetricsIngestionMessage } from '~/ingestion/pipelines/metrics/types'

import { MetricsRateLimiterService, metricsRateLimiterRedisErrorsCounter } from './metrics-rate-limiter.service'
import { METRICS_LIMITER_FAIL_OPEN_REDIS_TIMEOUT_MS } from './metrics-redis'

const message = (teamId: number): MetricsIngestionMessage => ({
    token: `token-${teamId}`,
    teamId,
    message: { headers: [] } as unknown as Message,
    bytesUncompressed: 1000,
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
})
