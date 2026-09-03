import { randomUUID } from 'crypto'

import { RedisOverflowRepository, redisKey } from '~/ingestion/common/overflow-redirect/overflow-redis-repository'
import { IngestionTestInfra, createIngestionTestInfra } from '~/tests/helpers/ingestion-e2e'

describe('RedisOverflowRepository (integration)', () => {
    let infra: IngestionTestInfra
    let repository: RedisOverflowRepository
    let testToken: string

    const key = (distinctId: string) => ({ token: testToken, distinctId })
    const memberKey = (distinctId: string) => `${testToken}:${distinctId}`

    beforeEach(async () => {
        infra = await createIngestionTestInfra()
        testToken = randomUUID()

        repository = new RedisOverflowRepository({
            redisPool: infra.redisPool,
            redisTTLSeconds: 300,
        })
    })

    afterEach(async () => {
        const redis = await infra.redisPool.acquire()
        const prefix = redisKey('events', testToken, '').replace('events:', '')
        const keys = await redis.keys(`${prefix}*`)
        if (keys.length) {
            await redis.del(...keys)
        }
        await infra.redisPool.release(redis)
        await infra.close()
    })

    describe('batchCheck', () => {
        it('returns false for keys that do not exist', async () => {
            const result = await repository.batchCheck('events', [key('user1')])

            expect(result.get(memberKey('user1'))).toBe(false)
        })

        it('returns true for keys that exist', async () => {
            const redis = await infra.redisPool.acquire()
            await redis.set(redisKey('events', testToken, 'user1'), '1')
            await infra.redisPool.release(redis)

            const result = await repository.batchCheck('events', [key('user1')])

            expect(result.get(memberKey('user1'))).toBe(true)
        })

        it('handles mixed existing and non-existing keys', async () => {
            const redis = await infra.redisPool.acquire()
            await redis.set(redisKey('events', testToken, 'user2'), '1')
            await infra.redisPool.release(redis)

            const result = await repository.batchCheck('events', [key('user1'), key('user2'), key('user3')])

            expect(result.get(memberKey('user1'))).toBe(false)
            expect(result.get(memberKey('user2'))).toBe(true)
            expect(result.get(memberKey('user3'))).toBe(false)
        })

        it('returns empty map for empty input', async () => {
            const result = await repository.batchCheck('events', [])

            expect(result.size).toBe(0)
        })
    })

    describe('batchFlag', () => {
        it('creates keys with TTL', async () => {
            await repository.batchFlag('events', [key('user1')])

            const redis = await infra.redisPool.acquire()
            const value = await redis.get(redisKey('events', testToken, 'user1'))
            const ttl = await redis.ttl(redisKey('events', testToken, 'user1'))
            await infra.redisPool.release(redis)

            expect(value).toBe('1')
            expect(ttl).toBeGreaterThan(0)
            expect(ttl).toBeLessThanOrEqual(300)
        })

        it('flags multiple keys in a single call', async () => {
            await repository.batchFlag('events', [key('user1'), key('user2')])

            const redis = await infra.redisPool.acquire()
            const val1 = await redis.get(redisKey('events', testToken, 'user1'))
            const val2 = await redis.get(redisKey('events', testToken, 'user2'))
            await infra.redisPool.release(redis)

            expect(val1).toBe('1')
            expect(val2).toBe('1')
        })

        it('does nothing for empty input', async () => {
            await repository.batchFlag('events', [])
            // No assertion needed - just shouldn't throw
        })
    })

    describe('batchRefreshTTL', () => {
        it('refreshes TTL for existing keys', async () => {
            const redis = await infra.redisPool.acquire()
            // Set key with short TTL
            await redis.set(redisKey('events', testToken, 'user1'), '1', 'EX', 10)
            await infra.redisPool.release(redis)

            // Refresh TTL to 300
            await repository.batchRefreshTTL('events', [key('user1')])

            const redis2 = await infra.redisPool.acquire()
            const ttl = await redis2.ttl(redisKey('events', testToken, 'user1'))
            await infra.redisPool.release(redis2)

            // TTL should now be close to 300 (the configured value)
            expect(ttl).toBeGreaterThan(200)
            expect(ttl).toBeLessThanOrEqual(300)
        })

        it('does not create keys that do not exist', async () => {
            await repository.batchRefreshTTL('events', [key('nonexistent')])

            const redis = await infra.redisPool.acquire()
            const exists = await redis.exists(redisKey('events', testToken, 'nonexistent'))
            await infra.redisPool.release(redis)

            expect(exists).toBe(0)
        })

        it('handles mixed existing and non-existing keys', async () => {
            const redis = await infra.redisPool.acquire()
            await redis.set(redisKey('events', testToken, 'existing'), '1', 'EX', 10)
            await infra.redisPool.release(redis)

            await repository.batchRefreshTTL('events', [key('existing'), key('nonexistent')])

            const redis2 = await infra.redisPool.acquire()
            const existingTTL = await redis2.ttl(redisKey('events', testToken, 'existing'))
            const nonexistentExists = await redis2.exists(redisKey('events', testToken, 'nonexistent'))
            await infra.redisPool.release(redis2)

            expect(existingTTL).toBeGreaterThan(200)
            expect(nonexistentExists).toBe(0)
        })

        it('does nothing for empty input', async () => {
            await repository.batchRefreshTTL('events', [])
            // No assertion needed - just shouldn't throw
        })
    })

    describe('batchFlag + batchCheck roundtrip', () => {
        it('keys flagged with batchFlag are found by batchCheck', async () => {
            await repository.batchFlag('events', [key('user1'), key('user2')])

            const result = await repository.batchCheck('events', [key('user1'), key('user2'), key('user3')])

            expect(result.get(memberKey('user1'))).toBe(true)
            expect(result.get(memberKey('user2'))).toBe(true)
            expect(result.get(memberKey('user3'))).toBe(false)
        })
    })

    describe('overflow type isolation', () => {
        it('keys for different overflow types are independent', async () => {
            await repository.batchFlag('events', [key('user1')])

            const eventsResult = await repository.batchCheck('events', [key('user1')])
            const recordingsResult = await repository.batchCheck('recordings', [key('user1')])

            expect(eventsResult.get(memberKey('user1'))).toBe(true)
            expect(recordingsResult.get(memberKey('user1'))).toBe(false)
        })
    })

    describe('healthCheck', () => {
        it('returns ok when Redis is available', async () => {
            const result = await repository.healthCheck()

            expect(result.status).toBe('ok')
        })
    })
})
