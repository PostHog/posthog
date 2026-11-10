import { randomInt, randomUUID } from 'crypto'
import { Redis } from 'ioredis'

import { defaultConfig } from '~/common/config/config'
import { deleteKeysWithPrefix } from '~/common/redis/_tests/redis'
import { RedisClient, RedisClientPipeline, RedisV2, createRedisV2PoolFromConfig } from '~/common/redis/redis-v2'
import { createRedisFromConfig } from '~/common/utils/db/redis'

import { RateLimiterService } from '../../rate-limiter/rate-limiter.service'
import { claimSandboxCaps } from './sandbox-caps'

describe('claimSandboxCaps', () => {
    let client: Redis
    let redis: RedisV2
    let limiter: RateLimiterService
    let organizationId: string
    let teamId: number

    const claim = (caps: { team: number; recipient: number }, storedAddress: string, team = teamId) =>
        claimSandboxCaps(limiter, caps, { organizationId, teamId: team, storedAddress, claimId: randomUUID() })

    beforeAll(async () => {
        client = await createRedisFromConfig(
            defaultConfig.CDP_REDIS_HOST
                ? {
                      url: defaultConfig.CDP_REDIS_HOST,
                      options: { port: defaultConfig.CDP_REDIS_PORT, password: defaultConfig.CDP_REDIS_PASSWORD },
                  }
                : { url: defaultConfig.REDIS_URL }
        )
        redis = {
            useClient: (_options, callback) => callback(client as unknown as RedisClient),
            usePipeline: (_options, callback) => {
                const pipeline = client.pipeline() as unknown as RedisClientPipeline
                callback(pipeline)
                return pipeline.exec()
            },
        }
        limiter = new RateLimiterService(redis, { name: 'sandbox-email-caps' })
    })

    afterAll(async () => {
        await client.quit()
    })

    beforeEach(() => {
        organizationId = randomUUID()
        teamId = randomInt(1_000_000_000)
    })

    afterEach(async () => {
        await deleteKeysWithPrefix(redis, `@posthog/sandbox-email/{${organizationId}}/`)
    })

    it('admits a first send', async () => {
        expect(await claim({ team: 5, recipient: 1 }, 'member@example.com')).toEqual({ ok: true })
    })

    it('stops a second send to one member once the recipient cap is reached, whatever the address case', async () => {
        await claim({ team: 5, recipient: 1 }, 'member@example.com')

        expect(await claim({ team: 5, recipient: 1 }, 'Member@Example.com')).toEqual({
            ok: false,
            reason: 'daily_cap_reached',
        })
        expect(await claim({ team: 5, recipient: 1 }, 'other@example.com')).toEqual({ ok: true })
    })

    it('shares the recipient cap across the projects of one organization', async () => {
        await claim({ team: 5, recipient: 1 }, 'member@example.com', teamId)

        expect(await claim({ team: 5, recipient: 1 }, 'member@example.com', teamId + 1)).toEqual({
            ok: false,
            reason: 'daily_cap_reached',
        })
    })

    it('stops sends to new members once the project cap is reached', async () => {
        await claim({ team: 1, recipient: 5 }, 'first@example.com')

        expect(await claim({ team: 1, recipient: 5 }, 'second@example.com')).toEqual({
            ok: false,
            reason: 'daily_cap_reached',
        })
    })

    it.each([
        ['project', { team: 1, recipient: 2 }, 'member@example.com', 1],
        ['recipient', { team: 2, recipient: 1 }, 'other@example.com', 0],
    ])('charges neither bucket when the %s bucket is full', async (_full, caps, nextAddress, teamOffset) => {
        await claim(caps, 'member@example.com')

        expect(await claim(caps, 'member@example.com')).toEqual({ ok: false, reason: 'daily_cap_reached' })
        expect(await claim(caps, nextAddress, teamId + teamOffset)).toEqual({ ok: true })
    })

    it('charges a retried claim once when Valkey ran the first attempt but its reply was lost', async () => {
        const replyLost: RedisV2 = {
            ...redis,
            useClient: async (options, callback) => {
                await redis.useClient(options, callback)
                throw new Error('Connection reset before the reply arrived')
            },
        }
        const caps = { team: 5, recipient: 2 }
        const sendAttempt = { organizationId, teamId, storedAddress: 'member@example.com', claimId: randomUUID() }

        expect(
            await claimSandboxCaps(new RateLimiterService(replyLost, { name: 'reply-lost' }), caps, sendAttempt)
        ).toEqual({ ok: false, reason: 'cap_storage_unavailable' })
        expect(await claimSandboxCaps(limiter, caps, sendAttempt)).toEqual({ ok: true })
        expect(await claim(caps, 'member@example.com')).toEqual({ ok: true })
        expect(await claim(caps, 'member@example.com')).toEqual({ ok: false, reason: 'daily_cap_reached' })
    })

    it('charges neither bucket when storage fails partway through the claim', async () => {
        await claim({ team: 5, recipient: 2 }, 'warmup@example.com')
        const [projectKey] =
            (await redis.useClient({ name: 'find-project-bucket' }, (client) =>
                client.keys(`@posthog/sandbox-email/*project/${teamId}`)
            )) ?? []
        await redis.useClient({ name: 'corrupt-project-bucket' }, (client) => client.set(projectKey, 'not a bucket'))

        expect(await claim({ team: 5, recipient: 1 }, 'member@example.com')).toEqual({
            ok: false,
            reason: 'cap_storage_unavailable',
        })

        await redis.useClient({ name: 'repair-project-bucket' }, (client) => client.del(projectKey))
        expect(await claim({ team: 5, recipient: 1 }, 'member@example.com')).toEqual({ ok: true })
    })

    it('reports an unreachable limiter as storage that cannot be read', async () => {
        const unreachable = createRedisV2PoolFromConfig({
            connection: {
                url: '127.0.0.1',
                options: { port: 1, commandTimeout: 100, retryStrategy: () => null },
                name: 'sandbox-caps-unreachable',
                exitOnRepeatedErrors: false,
            },
            poolMinSize: 0,
            poolMaxSize: 1,
            acquireTimeoutMillis: 100,
        })
        const broken = new RateLimiterService(unreachable, { name: 'broken' })

        expect(
            await claimSandboxCaps(
                broken,
                { team: 5, recipient: 5 },
                { organizationId, teamId, storedAddress: 'member@example.com', claimId: randomUUID() }
            )
        ).toEqual({ ok: false, reason: 'cap_storage_unavailable' })
    })

    it.each([
        ['a zero project cap', { team: 0, recipient: 5 }],
        ['a fractional recipient cap', { team: 5, recipient: 1.5 }],
        ['a missing project cap', { team: NaN, recipient: 5 }],
        ['a negative recipient cap', { team: 5, recipient: -1 }],
    ])('fails closed on %s without claiming a token', async (_case, caps) => {
        expect(await claim(caps, 'member@example.com')).toEqual({ ok: false, reason: 'cap_storage_unavailable' })
        expect(await claim({ team: 1, recipient: 1 }, 'member@example.com')).toEqual({ ok: true })
    })
})
