import { Hub } from '../../../types'
import { closeHub, createHub } from '../../../utils/db/hub'
import { RedisOverflowRepository, redisKey } from './overflow-redis-repository'

describe('RedisOverflowRepository (integration)', () => {
    let hub: Hub
    let repository: RedisOverflowRepository

    beforeEach(async () => {
        hub = await createHub()

        const redis = await hub.redisPool.acquire()
        await redis.flushdb()
        await hub.redisPool.release(redis)

        repository = new RedisOverflowRepository({
            redisPool: hub.redisPool,
            redisTTLSeconds: 300,
        })
    })

    afterEach(async () => {
        await closeHub(hub)
    })

    describe('batchCheck', () => {
        it('returns false for keys that do not exist', async () => {
            const result = await repository.batchCheck('events', [{ token: 'token1', distinctId: 'user1' }])

            expect(result.get('token1:user1')).toBe(false)
        })

        it('returns true for keys that exist', async () => {
            const redis = await hub.redisPool.acquire()
            await redis.set(redisKey('events', 'token1', 'user1'), '1')
            await hub.redisPool.release(redis)

            const result = await repository.batchCheck('events', [{ token: 'token1', distinctId: 'user1' }])

            expect(result.get('token1:user1')).toBe(true)
        })

        it('handles mixed existing and non-existing keys', async () => {
            const redis = await hub.redisPool.acquire()
            await redis.set(redisKey('events', 'token1', 'user2'), '1')
            await hub.redisPool.release(redis)

            const result = await repository.batchCheck('events', [
                { token: 'token1', distinctId: 'user1' },
                { token: 'token1', distinctId: 'user2' },
                { token: 'token1', distinctId: 'user3' },
            ])

            expect(result.get('token1:user1')).toBe(false)
            expect(result.get('token1:user2')).toBe(true)
            expect(result.get('token1:user3')).toBe(false)
        })

        it('returns empty map for empty input', async () => {
            const result = await repository.batchCheck('events', [])

            expect(result.size).toBe(0)
        })
    })

    describe('batchFlag', () => {
        it('creates keys with TTL', async () => {
            await repository.batchFlag('events', [{ token: 'token1', distinctId: 'user1' }])

            const redis = await hub.redisPool.acquire()
            const value = await redis.get(redisKey('events', 'token1', 'user1'))
            const ttl = await redis.ttl(redisKey('events', 'token1', 'user1'))
            await hub.redisPool.release(redis)

            expect(value).toBe('1')
            expect(ttl).toBeGreaterThan(0)
            expect(ttl).toBeLessThanOrEqual(300)
        })

        it('flags multiple keys in a single call', async () => {
            await repository.batchFlag('events', [
                { token: 'token1', distinctId: 'user1' },
                { token: 'token1', distinctId: 'user2' },
            ])

            const redis = await hub.redisPool.acquire()
            const val1 = await redis.get(redisKey('events', 'token1', 'user1'))
            const val2 = await redis.get(redisKey('events', 'token1', 'user2'))
            await hub.redisPool.release(redis)

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
            const redis = await hub.redisPool.acquire()
            // Set key with short TTL
            await redis.set(redisKey('events', 'token1', 'user1'), '1', 'EX', 10)
            await hub.redisPool.release(redis)

            // Refresh TTL to 300
            await repository.batchRefreshTTL('events', [{ token: 'token1', distinctId: 'user1' }])

            const redis2 = await hub.redisPool.acquire()
            const ttl = await redis2.ttl(redisKey('events', 'token1', 'user1'))
            await hub.redisPool.release(redis2)

            // TTL should now be close to 300 (the configured value)
            expect(ttl).toBeGreaterThan(200)
            expect(ttl).toBeLessThanOrEqual(300)
        })

        it('does not create keys that do not exist', async () => {
            await repository.batchRefreshTTL('events', [{ token: 'token1', distinctId: 'nonexistent' }])

            const redis = await hub.redisPool.acquire()
            const exists = await redis.exists(redisKey('events', 'token1', 'nonexistent'))
            await hub.redisPool.release(redis)

            expect(exists).toBe(0)
        })

        it('handles mixed existing and non-existing keys', async () => {
            const redis = await hub.redisPool.acquire()
            await redis.set(redisKey('events', 'token1', 'existing'), '1', 'EX', 10)
            await hub.redisPool.release(redis)

            await repository.batchRefreshTTL('events', [
                { token: 'token1', distinctId: 'existing' },
                { token: 'token1', distinctId: 'nonexistent' },
            ])

            const redis2 = await hub.redisPool.acquire()
            const existingTTL = await redis2.ttl(redisKey('events', 'token1', 'existing'))
            const nonexistentExists = await redis2.exists(redisKey('events', 'token1', 'nonexistent'))
            await hub.redisPool.release(redis2)

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
            await repository.batchFlag('events', [
                { token: 'token1', distinctId: 'user1' },
                { token: 'token1', distinctId: 'user2' },
            ])

            const result = await repository.batchCheck('events', [
                { token: 'token1', distinctId: 'user1' },
                { token: 'token1', distinctId: 'user2' },
                { token: 'token1', distinctId: 'user3' },
            ])

            expect(result.get('token1:user1')).toBe(true)
            expect(result.get('token1:user2')).toBe(true)
            expect(result.get('token1:user3')).toBe(false)
        })
    })

    describe('overflow type isolation', () => {
        it('keys for different overflow types are independent', async () => {
            await repository.batchFlag('events', [{ token: 'token1', distinctId: 'user1' }])

            const eventsResult = await repository.batchCheck('events', [{ token: 'token1', distinctId: 'user1' }])
            const recordingsResult = await repository.batchCheck('recordings', [
                { token: 'token1', distinctId: 'user1' },
            ])

            expect(eventsResult.get('token1:user1')).toBe(true)
            expect(recordingsResult.get('token1:user1')).toBe(false)
        })
    })

    describe('healthCheck', () => {
        it('returns ok when Redis is available', async () => {
            const result = await repository.healthCheck()

            expect(result.status).toBe('ok')
        })
    })
})
