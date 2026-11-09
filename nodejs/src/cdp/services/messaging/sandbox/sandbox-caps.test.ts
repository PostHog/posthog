import { randomInt, randomUUID } from 'crypto'

import { deleteKeysWithPrefix } from '~/common/redis/_tests/redis'
import { RedisV2, createRedisV2PoolFromConfig } from '~/common/redis/redis-v2'
import { closeHub, createHub } from '~/common/utils/db/hub'
import { Hub } from '~/types'

import { RateLimiterService } from '../../rate-limiter/rate-limiter.service'
import { claimSandboxCaps } from './sandbox-caps'

describe('claimSandboxCaps', () => {
    let hub: Hub
    let redis: RedisV2
    let limiter: RateLimiterService
    let organizationId: string
    let teamId: number

    const claim = (caps: { team: number; recipient: number }, storedAddress: string, team = teamId) =>
        claimSandboxCaps(limiter, caps, { organizationId, teamId: team, storedAddress })

    beforeAll(async () => {
        hub = await createHub()
        redis = createRedisV2PoolFromConfig({
            connection: hub.CDP_REDIS_HOST
                ? {
                      url: hub.CDP_REDIS_HOST,
                      options: { port: hub.CDP_REDIS_PORT, password: hub.CDP_REDIS_PASSWORD },
                  }
                : { url: hub.REDIS_URL },
            poolMinSize: hub.REDIS_POOL_MIN_SIZE,
            poolMaxSize: hub.REDIS_POOL_MAX_SIZE,
        })
        limiter = new RateLimiterService(redis, { name: 'sandbox-email-caps' })
    })

    afterAll(async () => {
        await closeHub(hub)
    })

    beforeEach(() => {
        organizationId = randomUUID()
        teamId = randomInt(1_000_000_000)
    })

    afterEach(async () => {
        await deleteKeysWithPrefix(redis, `@posthog/sandbox-email/recipient/${organizationId}/`)
        for (const team of [teamId, teamId + 1]) {
            await deleteKeysWithPrefix(redis, `@posthog/sandbox-email/project/${team}`)
        }
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

    it('reports an unreachable limiter as storage that cannot be read', async () => {
        const broken = new RateLimiterService(
            { useClient: jest.fn().mockRejectedValue(new Error('connection lost')) } as unknown as RedisV2,
            { name: 'broken' }
        )

        expect(
            await claimSandboxCaps(
                broken,
                { team: 5, recipient: 5 },
                { organizationId, teamId, storedAddress: 'member@example.com' }
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
