import { randomInt, randomUUID } from 'crypto'
import { Redis } from 'ioredis'
import { register } from 'prom-client'

import { defaultConfig } from '~/common/config/config'
import { deleteKeysWithPrefix } from '~/common/redis/_tests/redis'
import { StallingValkeyProxy } from '~/common/redis/_tests/stalling-valkey-proxy'
import {
    MAX_PENDING_ACQUIRES_WITH_DEADLINE,
    RedisClient,
    RedisClientPipeline,
    RedisV2,
    createRedisV2PoolFromConfig,
} from '~/common/redis/redis-v2'
import { createRedisFromConfig } from '~/common/utils/db/redis'
import { waitForExpect } from '~/tests/helpers/expectations'

import { CLAIM_DEADLINE_MS, RateLimiterService } from '../../rate-limiter/rate-limiter.service'
import { SandboxCapClaim, SandboxCaps, claimSandboxCaps } from './sandbox-caps'

describe('claimSandboxCaps', () => {
    let client: Redis
    let redis: RedisV2
    let limiter: RateLimiterService
    let organizationId: string
    let teamId: number

    const claim = (caps: SandboxCaps, team = teamId) =>
        claimSandboxCaps(limiter, caps, { organizationId, teamId: team, claimId: randomUUID() })

    const sameSend = () => ({ organizationId, teamId, claimId: randomUUID() })

    const warnings = async (): Promise<number> =>
        (await register.getSingleMetric('cdp_sandbox_email_team_warning_total')!.get()).values[0]?.value ?? 0

    type Granted = Extract<SandboxCapClaim, { ok: true }>

    const granted = (result: SandboxCapClaim): Granted => {
        if (!result.ok) {
            throw new Error(`expected a granted claim, got ${result.reason}`)
        }
        return result
    }

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
        expect(await claim({ team: 5, warning: 5 })).toMatchObject({ ok: true })
    })

    it('stops sends once the project cap is reached, and keeps the other projects of the organization apart', async () => {
        await claim({ team: 1, warning: 5 })

        expect(await claim({ team: 1, warning: 5 })).toEqual({ ok: false, reason: 'daily_cap_reached' })
        expect(await claim({ team: 1, warning: 5 }, teamId + 1)).toMatchObject({ ok: true })
    })

    it('counts sends past the warning threshold without refusing them, and a retried send only once', async () => {
        const caps = { team: 5, warning: 1 }
        const before = await warnings()
        const firstSend = sameSend()
        await claimSandboxCaps(limiter, caps, firstSend)

        expect(await claimSandboxCaps(limiter, caps, firstSend)).toMatchObject({ ok: true })
        expect(await warnings()).toBe(before)
        expect(await claim(caps)).toMatchObject({ ok: true })
        expect(await warnings()).toBe(before + 1)
    })

    it('charges a retried claim once when Valkey ran the first attempt but its reply was lost', async () => {
        const replyLost: RedisV2 = {
            ...redis,
            useClient: async (options, callback) => {
                await redis.useClient(options, callback)
                throw new Error('Connection reset before the reply arrived')
            },
        }
        const caps = { team: 2, warning: 5 }
        const sendAttempt = sameSend()

        expect(
            await claimSandboxCaps(new RateLimiterService(replyLost, { name: 'reply-lost' }), caps, sendAttempt)
        ).toEqual({ ok: false, reason: 'cap_storage_unavailable' })
        const retry = granted(await claimSandboxCaps(limiter, caps, sendAttempt))
        expect(await retry.markSending()).toBe(true)
        expect(await claim(caps)).toMatchObject({ ok: true })
        expect(await claim(caps)).toEqual({ ok: false, reason: 'daily_cap_reached' })
    })

    it('charges a replayed claim again once an attempt marked it sending, whether or not that send finished', async () => {
        const caps = { team: 2, warning: 5 }
        const sendAttempt = sameSend()
        const first = granted(await claimSandboxCaps(limiter, caps, sendAttempt))
        expect(await first.markSending()).toBe(true)

        expect(await claimSandboxCaps(limiter, caps, sendAttempt)).toMatchObject({ ok: true })
        expect(await claim(caps)).toEqual({ ok: false, reason: 'daily_cap_reached' })
    })

    it('lets a replay reuse the charge for free once the sending attempt released its unsent claim', async () => {
        const caps = { team: 2, warning: 5 }
        const sendAttempt = sameSend()
        const first = granted(await claimSandboxCaps(limiter, caps, sendAttempt))
        expect(await first.markSending()).toBe(true)
        expect(await first.releaseUnsent()).toBe(true)

        const retry = granted(await claimSandboxCaps(limiter, caps, sendAttempt))
        expect(await retry.markSending()).toBe(true)
        expect(await claim(caps)).toMatchObject({ ok: true })
        expect(await claim(caps)).toEqual({ ok: false, reason: 'daily_cap_reached' })
    })

    it.each([
        ['sending mark', (claim: Granted) => claim.markSending()],
        ['release', (claim: Granted) => claim.releaseUnsent()],
    ])("keeps a replay's charge when the earlier charge's %s arrives late", async (_late, late) => {
        const caps = { team: 2, warning: 5 }
        const sendAttempt = sameSend()
        const first = granted(await claimSandboxCaps(limiter, caps, sendAttempt))
        await first.markSending()
        const replay = granted(await claimSandboxCaps(limiter, caps, sendAttempt))
        expect(await replay.markSending()).toBe(true)

        expect(await late(first)).toBe(false)
        expect(await claimSandboxCaps(limiter, caps, sendAttempt)).toEqual({ ok: false, reason: 'daily_cap_reached' })
    })

    it('lets only one of two overlapping attempts on one charge send, and only that one release it', async () => {
        const caps = { team: 1, warning: 1 }
        const sendAttempt = sameSend()
        const first = granted(await claimSandboxCaps(limiter, caps, sendAttempt))
        const overlapping = granted(await claimSandboxCaps(limiter, caps, sendAttempt))

        expect(await first.markSending()).toBe(true)
        expect(await overlapping.markSending()).toBe(false)
        expect(await overlapping.releaseUnsent()).toBe(false)
        expect(await claimSandboxCaps(limiter, caps, sendAttempt)).toEqual({ ok: false, reason: 'daily_cap_reached' })
    })

    it('charges a reused claim id again when it names another project', async () => {
        const caps = { team: 1, warning: 5 }
        const claimId = randomUUID()
        await claimSandboxCaps(limiter, caps, { organizationId, teamId, claimId })

        expect(await claimSandboxCaps(limiter, caps, { organizationId, teamId: teamId + 1, claimId })).toMatchObject({
            ok: true,
        })
        expect(await claim(caps, teamId + 1)).toEqual({ ok: false, reason: 'daily_cap_reached' })
    })

    it('refuses a send while its project bucket cannot be read, and claims again once it can', async () => {
        await claim({ team: 5, warning: 5 })
        const [projectKey] =
            (await redis.useClient({ name: 'find-project-bucket' }, (client) =>
                client.keys(`@posthog/sandbox-email/*project/${teamId}`)
            )) ?? []
        await redis.useClient({ name: 'corrupt-project-bucket' }, (client) => client.set(projectKey, 'not a bucket'))

        expect(await claim({ team: 5, warning: 5 })).toEqual({ ok: false, reason: 'cap_storage_unavailable' })

        await redis.useClient({ name: 'repair-project-bucket' }, (client) => client.del(projectKey))
        expect(await claim({ team: 5, warning: 5 })).toMatchObject({ ok: true })
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
            await claimSandboxCaps(broken, { team: 5, warning: 5 }, { organizationId, teamId, claimId: randomUUID() })
        ).toEqual({ ok: false, reason: 'cap_storage_unavailable' })
    })

    describe('on a Valkey pool with no deadlines of its own', () => {
        let store: StallingValkeyProxy
        let stalling: RateLimiterService
        let storePort: number
        const caps = { team: 5, warning: 5 }
        const unavailable = { ok: false, reason: 'cap_storage_unavailable' }

        const answerWithin = <T>(work: Promise<T>, ms: number): Promise<T | 'no answer'> => {
            let gaveUp: NodeJS.Timeout | undefined
            return Promise.race([
                work,
                new Promise<'no answer'>((resolve) => {
                    gaveUp = setTimeout(() => resolve('no answer'), ms)
                }),
            ]).finally(() => clearTimeout(gaveUp))
        }

        const limiterThrough = (port: number, poolMaxSize: number): RateLimiterService =>
            new RateLimiterService(
                createRedisV2PoolFromConfig({
                    connection: {
                        url: '127.0.0.1',
                        options: { port, password: defaultConfig.CDP_REDIS_PASSWORD, retryStrategy: () => null },
                        name: 'sandbox-caps-stalling',
                        exitOnRepeatedErrors: false,
                    },
                    poolMinSize: 0,
                    poolMaxSize,
                }),
                { name: 'stalling' }
            )

        beforeEach(async () => {
            store = new StallingValkeyProxy({ host: defaultConfig.CDP_REDIS_HOST, port: defaultConfig.CDP_REDIS_PORT })
            storePort = await store.start()
            stalling = limiterThrough(storePort, 1)
        })

        afterEach(() => {
            store.stop()
        })

        it('answers unavailable when storage stops replying, and claims again on a fresh connection', async () => {
            const first = granted(await claimSandboxCaps(stalling, caps, sameSend()))

            store.stopAnsweringOpenConnections()
            expect(await answerWithin(claimSandboxCaps(stalling, caps, sameSend()), 10_000)).toEqual(unavailable)
            expect(await answerWithin(claimSandboxCaps(stalling, caps, sameSend()), 10_000)).toMatchObject({ ok: true })

            store.stopAnsweringOpenConnections()
            expect(await answerWithin(first.markSending(), 10_000)).toBe(false)

            store.stopAnswering()
            expect(await answerWithin(first.releaseUnsent(), 10_000)).toBe(false)

            store.answerNewConnections()
            await waitForExpect(
                async () => expect(await claimSandboxCaps(stalling, caps, sameSend())).toMatchObject({ ok: true }),
                30_000
            )
        })

        it('refuses at once while abandoned claims still wait for a connection, and claims again once storage answers', async () => {
            store.stopAnswering()
            const abandoned = await Promise.all(
                Array.from({ length: MAX_PENDING_ACQUIRES_WITH_DEADLINE }, () =>
                    claimSandboxCaps(stalling, caps, sameSend())
                )
            )
            expect(abandoned).toEqual(abandoned.map(() => unavailable))

            expect(await answerWithin(claimSandboxCaps(stalling, caps, sameSend()), CLAIM_DEADLINE_MS / 2)).toEqual(
                unavailable
            )

            store.answerNewConnections()
            await waitForExpect(
                async () => expect(await claimSandboxCaps(stalling, caps, sameSend())).toMatchObject({ ok: true }),
                30_000
            )
        })

        it('opens at most that many connections to storage that stops answering a burst of claims', async () => {
            const wide = limiterThrough(storePort, 3 * MAX_PENDING_ACQUIRES_WITH_DEADLINE)
            store.stopAnswering()

            const burst = await Promise.all(
                Array.from({ length: 3 * MAX_PENDING_ACQUIRES_WITH_DEADLINE }, () =>
                    claimSandboxCaps(wide, caps, sameSend())
                )
            )

            expect(burst).toEqual(burst.map(() => unavailable))
            expect(store.openConnections).toBeLessThanOrEqual(MAX_PENDING_ACQUIRES_WITH_DEADLINE)

            store.answerNewConnections()
            await waitForExpect(
                async () => expect(await claimSandboxCaps(wide, caps, sameSend())).toMatchObject({ ok: true }),
                30_000
            )
        })

        it('claims a burst of more sends than that limit on one connection while storage answers', async () => {
            const roomy = { team: 100, warning: 100 }

            const burst = await Promise.all(
                Array.from({ length: 3 * MAX_PENDING_ACQUIRES_WITH_DEADLINE }, () =>
                    claimSandboxCaps(stalling, roomy, sameSend())
                )
            )

            expect(burst).toEqual(burst.map(() => expect.objectContaining({ ok: true })))
        })
    })

    it.each([
        ['a zero project cap', { team: 0, warning: 5 }],
        ['a fractional warning threshold', { team: 5, warning: 1.5 }],
        ['a missing project cap', { team: NaN, warning: 5 }],
        ['a negative warning threshold', { team: 5, warning: -1 }],
    ])('fails closed on %s without claiming a token', async (_case, caps) => {
        expect(await claim(caps)).toEqual({ ok: false, reason: 'cap_storage_unavailable' })
        expect(await claim({ team: 1, warning: 1 })).toMatchObject({ ok: true })
    })
})
