import { randomUUID } from 'crypto'
import { AddressInfo, Server, Socket, createServer } from 'net'
import { register } from 'prom-client'

import { deleteKeysWithPrefix } from '~/common/redis/_tests/redis'
import { RedisClient, RedisV2, createRedisV2PoolFromConfig } from '~/common/redis/redis-v2'
import { closeHub, createHub } from '~/common/utils/db/hub'
import { TeamManager } from '~/common/utils/team-manager'
import { Hub } from '~/types'

import { createSandboxDailyCapLimiter } from '../../cdp-services'
import { getDefaultCdpConfig } from '../../config'
import { createEmailActionValkeys } from '../../email-action-valkeys'
import { SandboxEmailSender } from '../messaging/sandbox-email-sender'
import { createSesRateLimiterValkeyPool } from './rate-limiter-valkey-pool'
import { ClaimRequest, IssuedClaim, RateLimiterService } from './rate-limiter.service'

const KEY = `@posthog-test/ses-rate-limiter/${randomUUID()}/bucket`

const INFO = 'redis_version:7.2.0\r\nloading:0'

function stallingValkey(): {
    server: Server
    sockets: Set<Socket>
    stall: () => void
    commandsWhileStalled: () => number
} {
    let stalled = false
    let received = 0
    const sockets = new Set<Socket>()
    const server = createServer((socket) => {
        sockets.add(socket)
        socket.on('close', () => sockets.delete(socket))
        socket.on('data', (chunk) => {
            const text = chunk.toString()
            for (const line of text.split('\r\n')) {
                if (!line.startsWith('*')) {
                    continue
                }
                if (stalled) {
                    received += 1
                    continue
                }
                socket.write(text.toLowerCase().includes('info') ? `$${INFO.length}\r\n${INFO}\r\n` : '+OK\r\n')
            }
        })
    })
    return {
        server,
        sockets,
        stall: () => {
            stalled = true
        },
        commandsWhileStalled: () => received,
    }
}

describe('RateLimiterService', () => {
    jest.retryTimes(3, { logErrorsBeforeRetry: true })

    let hub: Hub
    let redis: RedisV2
    let limiter: RateLimiterService

    beforeEach(async () => {
        hub = await createHub()
        // Reuse the local CDP Redis for tests — same wire protocol, same atomicity.
        // In production this points at the dedicated SES rate-limiter Valkey.
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
        limiter = new RateLimiterService(redis, { name: 'ses-rate-limiter' })
        await deleteKeysWithPrefix(redis, KEY)
    })

    afterEach(async () => {
        await closeHub(hub)
    })

    it('cold-starts at full capacity', async () => {
        const granted = await limiter.claimUpTo({
            key: KEY,
            requested: 50,
            capacity: 50,
            refillPerSecond: 100,
        })
        expect(granted).toBe(50)
    })

    it('returns 0 when the bucket is drained', async () => {
        await limiter.claimUpTo({ key: KEY, requested: 50, capacity: 50, refillPerSecond: 100 })
        // Second claim immediately after — refill in 0ms is negligible, ~0 tokens available
        const granted = await limiter.claimUpTo({
            key: KEY,
            requested: 50,
            capacity: 50,
            refillPerSecond: 100,
        })
        expect(granted).toBeLessThan(5)
    })

    it('grants partial when fewer tokens are available than requested', async () => {
        // First, drain 40 of 50.
        await limiter.claimUpTo({ key: KEY, requested: 40, capacity: 50, refillPerSecond: 0 })
        // refillPerSecond=0 keeps the residual at exactly 10 tokens.
        const granted = await limiter.claimUpTo({
            key: KEY,
            requested: 50,
            capacity: 50,
            refillPerSecond: 0,
        })
        expect(granted).toBe(10)
    })

    it('refills tokens over time', async () => {
        await limiter.claimUpTo({ key: KEY, requested: 50, capacity: 50, refillPerSecond: 100 })
        // Wait 200ms — at 100 tokens/sec, ~20 tokens should refill.
        await new Promise((resolve) => setTimeout(resolve, 200))
        const granted = await limiter.claimUpTo({
            key: KEY,
            requested: 50,
            capacity: 50,
            refillPerSecond: 100,
        })
        // Allow a wide margin — real-time-based, can vary on busy CI.
        expect(granted).toBeGreaterThanOrEqual(10)
        expect(granted).toBeLessThanOrEqual(30)
    })

    it('atomically serializes concurrent claims so the sum never exceeds capacity', async () => {
        // Two pods racing for the same bucket. Single Lua script per call → Valkey
        // serializes them, so the sum-of-grants is bounded by the bucket capacity.
        const N = 5
        const claims = await Promise.all(
            Array.from({ length: N }, () =>
                limiter.claimUpTo({ key: KEY, requested: 50, capacity: 50, refillPerSecond: 0 })
            )
        )
        const total = claims.reduce((a, b) => a + b, 0)
        expect(total).toBe(50)
        // Exactly one caller got the full bucket; the rest got 0.
        expect(claims.filter((c) => c > 0)).toHaveLength(1)
    })

    it('caps tokens at capacity even after long idle', async () => {
        await limiter.claimUpTo({ key: KEY, requested: 50, capacity: 50, refillPerSecond: 1000 })
        // Wait long enough that uncapped accrual would exceed capacity.
        await new Promise((resolve) => setTimeout(resolve, 100))
        const granted = await limiter.claimUpTo({
            key: KEY,
            requested: 1000,
            capacity: 50,
            refillPerSecond: 1000,
        })
        expect(granted).toBe(50)
    })

    describe('metric emission', () => {
        // Counters are module-scoped globals — use deltas (after − before) per
        // test so we don't have to reset shared state between runs.
        const readCounter = async (labels: Record<string, string>): Promise<number> => {
            const metric = register.getSingleMetric('cdp_rate_limiter_claim_total')
            if (!metric) {
                return 0
            }
            const data = await metric.get()
            return data.values
                .filter((v: any) =>
                    Object.entries(labels).every(([k, val]) => (v.labels as Record<string, string>)[k] === val)
                )
                .reduce((sum: number, v: any) => sum + v.value, 0)
        }

        it('increments granted_full when the grant equals the request', async () => {
            const labels = { limiter: 'ses-rate-limiter', result: 'granted_full' }
            const before = await readCounter(labels)

            const granted = await limiter.claimUpTo({ key: KEY, requested: 5, capacity: 10, refillPerSecond: 0 })
            expect(granted).toBe(5)

            const after = await readCounter(labels)
            expect(after - before).toBe(1)
        })

        it('increments granted_partial when the grant is less than the request', async () => {
            // Drain to 2 tokens, then ask for 5.
            await limiter.claimUpTo({ key: KEY, requested: 8, capacity: 10, refillPerSecond: 0 })

            const labels = { limiter: 'ses-rate-limiter', result: 'granted_partial' }
            const before = await readCounter(labels)

            const granted = await limiter.claimUpTo({ key: KEY, requested: 5, capacity: 10, refillPerSecond: 0 })
            expect(granted).toBe(2)

            const after = await readCounter(labels)
            expect(after - before).toBe(1)
        })

        it('increments denied when the bucket is empty', async () => {
            // Drain the bucket fully.
            await limiter.claimUpTo({ key: KEY, requested: 10, capacity: 10, refillPerSecond: 0 })

            const labels = { limiter: 'ses-rate-limiter', result: 'denied' }
            const before = await readCounter(labels)

            const granted = await limiter.claimUpTo({ key: KEY, requested: 5, capacity: 10, refillPerSecond: 0 })
            expect(granted).toBe(0)

            const after = await readCounter(labels)
            expect(after - before).toBe(1)
        })

        it('increments valkey_error when the Lua call throws', async () => {
            // Synthetic broken pool — useClient rejects on every call.
            const brokenValkey = {
                useClient: jest.fn().mockRejectedValue(new Error('connection lost')),
                usePipeline: jest.fn(),
            } as unknown as RedisV2
            const brokenLimiter = new RateLimiterService(brokenValkey, { name: 'broken-limiter' })

            const labels = { limiter: 'broken-limiter', result: 'valkey_error' }
            const before = await readCounter(labels)

            const granted = await brokenLimiter.claimUpTo({
                key: KEY,
                requested: 5,
                capacity: 10,
                refillPerSecond: 0,
            })
            // Fail-closed: thrown error → 0 granted.
            expect(granted).toBe(0)

            const after = await readCounter(labels)
            expect(after - before).toBe(1)
        })
    })

    describe('claimAllOrNothing', () => {
        const AON_KEY = `${KEY}/all-or-nothing`

        it('grants and charges the pool when the bucket covers the request', async () => {
            const claim = await limiter.claimAllOrNothing(
                { key: AON_KEY, requested: 30, capacity: 50, refillPerSecond: 0 },
                600_000
            )
            expect(claim).toEqual({ granted: true, retryAfterMs: null, reserved: false })
            // The remainder is all that is left to claim.
            expect(await limiter.claimUpTo({ key: AON_KEY, requested: 50, capacity: 50, refillPerSecond: 0 })).toBe(20)
        })

        it('consumes nothing on denial, so retries cannot starve the bucket', async () => {
            // The bucket cannot cover the request, so the claim must leave the pool untouched.
            // Without that, a rescheduled multi-recipient send would burn the refill on every
            // retry while never sending.
            const req = { key: `${AON_KEY}/denied`, requested: 30, capacity: 10, refillPerSecond: 0 }
            const claim = await limiter.claimAllOrNothing(req, 600_000)
            // refillPerSecond 0 means the missing tokens never accrue, so no horizon is reported.
            expect(claim).toEqual({ granted: false, retryAfterMs: null, reserved: false })
            expect(await limiter.claimUpTo({ ...req, requested: 10 })).toBe(10)
        })

        it('reports on denial how long until the missing tokens accrue', async () => {
            // Cold start: the bucket holds exactly its capacity of 10, so the request for 30 is
            // missing 20 tokens. At 2 tokens/s that is 10 seconds.
            const claim = await limiter.claimAllOrNothing(
                { key: `${AON_KEY}/horizon`, requested: 30, capacity: 10, refillPerSecond: 2 },
                600_000
            )
            expect(claim).toEqual({ granted: false, retryAfterMs: 10_000, reserved: true })
        })

        it('fails closed when the Lua call throws', async () => {
            const brokenValkey = {
                useClient: jest.fn().mockRejectedValue(new Error('connection lost')),
                usePipeline: jest.fn(),
            } as unknown as RedisV2
            const brokenLimiter = new RateLimiterService(brokenValkey, { name: 'broken-limiter' })
            // A null horizon is how the caller tells an unreachable limiter from a reached cap.
            const claim = await brokenLimiter.claimAllOrNothing(
                { key: AON_KEY, requested: 5, capacity: 50, refillPerSecond: 1 },
                600_000
            )
            expect(claim).toEqual({ granted: false, retryAfterMs: null, reserved: false })
        })
    })

    describe('claimOrReserve', () => {
        const RESERVE_KEY = `${KEY}/reserve`
        const req = { key: RESERVE_KEY, requested: 1, capacity: 2, refillPerSecond: 2 }

        it('grants normally without reserving a slot', async () => {
            const claim = await limiter.claimOrReserve(req, 60_000)
            expect(claim).toEqual({ granted: 1, retryAfterMs: null, reserved: false })
        })

        it('hands successive denials distinct, later slots', async () => {
            // Drain the bucket so every claim below is a full denial. At 2 tokens/s each
            // reservation advances the slot cursor by 500ms, so three denied callers park
            // at three different times instead of all retrying against the next token.
            await limiter.claimUpTo({ ...req, requested: 2 })

            const first = await limiter.claimOrReserve(req, 60_000)
            const second = await limiter.claimOrReserve(req, 60_000)
            const third = await limiter.claimOrReserve(req, 60_000)

            expect(first.granted).toBe(0)
            expect(first.retryAfterMs).toBeGreaterThan(0)
            // Strictly later each time; the spacing is ~500ms minus wall-clock elapsed
            // between calls, so bound it loosely rather than exactly.
            expect(second.retryAfterMs!).toBeGreaterThan(first.retryAfterMs!)
            expect(third.retryAfterMs!).toBeGreaterThan(second.retryAfterMs!)
            expect(third.retryAfterMs!).toBeLessThanOrEqual(1_500)
            // All three got their own slot, so each can park on it exactly.
            expect([first.reserved, second.reserved, third.reserved]).toEqual([true, true, true])
        })

        it('charges the first denial only for the tokens the bucket is short of', async () => {
            // One token takes 4s to refill. Drain the bucket, wait 1s so a quarter of a
            // token is back, then get denied. The slot must only cover what is still
            // missing (~3s), not the full 4s: the quarter token is credit already earned.
            const partialReq = { key: `${RESERVE_KEY}/partial`, requested: 1, capacity: 1, refillPerSecond: 0.25 }
            await limiter.claimUpTo(partialReq)
            await new Promise((resolve) => setTimeout(resolve, 1_000))

            const denial = await limiter.claimOrReserve(partialReq, 60_000)

            expect(denial.granted).toBe(0)
            expect(denial.reserved).toBe(true)
            // A slow test runner only makes the slot shorter (more refill happened).
            // Charging the full interval would report 4s and fail this bound.
            expect(denial.retryAfterMs).toBeGreaterThan(0)
            expect(denial.retryAfterMs).toBeLessThanOrEqual(3_000)
        })

        it('stops advancing the cursor at the horizon', async () => {
            // One 1s slot fits the 1s horizon. The first denial takes it; everyone after
            // just gets "come back in 1s" with no slot, so the cursor cannot run away.
            const slowReq = { key: `${RESERVE_KEY}/capped`, requested: 1, capacity: 1, refillPerSecond: 1 }
            await limiter.claimUpTo({ ...slowReq })

            const first = await limiter.claimOrReserve(slowReq, 1_000)
            const second = await limiter.claimOrReserve(slowReq, 1_000)
            const third = await limiter.claimOrReserve(slowReq, 1_000)

            expect(first.retryAfterMs).toBeLessThanOrEqual(1_000)
            expect(second.retryAfterMs).toBe(1_000)
            expect(third.retryAfterMs).toBe(1_000)
            // Only the first got a slot. The other two share one wake time and are told so,
            // which is the caller's cue to spread its own wake.
            expect([first.reserved, second.reserved, third.reserved]).toEqual([true, false, false])
        })
    })

    it('shares recipient allowances across projects in an organization while keeping project allowances separate', async () => {
        const organizations = { 1: randomUUID(), 3: randomUUID(), 4: randomUUID(), 6: randomUUID() }
        const teamManager = {
            getTeam: (id: number) =>
                id === 5
                    ? Promise.reject(new Error('Postgres is unreachable'))
                    : Promise.resolve({
                          organization_id: id in organizations ? organizations[id as 3 | 4 | 6] : organizations[1],
                      }),
        } as unknown as TeamManager
        const sender = new SandboxEmailSender(
            {
                enabled: true,
                tenantName: 'sandbox',
                configurationSetName: 'sandbox',
                fromAddress: 'sender@example.com',
                dailyTeamCap: '1',
                dailyRecipientCap: '1',
            },
            teamManager,
            redis,
            limiter
        )

        try {
            expect(await sender.claimDailyCaps(1, ['member@example.com'])).toMatchObject({ type: 'granted' })
            expect(await sender.claimDailyCaps(2, ['member@example.com'])).toEqual({
                type: 'recipient_cap_reached',
                addresses: ['member@example.com'],
            })
            expect(await sender.claimDailyCaps(2, ['other@example.com'])).toMatchObject({ type: 'granted' })
            expect(await sender.claimDailyCaps(3, ['member@example.com'])).toMatchObject({ type: 'granted' })
            expect(await sender.claimDailyCaps(2, ['third@example.com'])).toEqual({ type: 'project_cap_reached' })
            expect(await sender.claimDailyCaps(4, ['twice@example.com', ' twice@example.com'])).toEqual({
                type: 'project_cap_reached',
            })
            expect(await sender.claimDailyCaps(6, ['Member@example.com', 'member@example.com'])).toEqual({
                type: 'project_cap_reached',
            })
            expect(await sender.claimDailyCaps(5, ['member@example.com'])).toEqual({ type: 'check_failed' })
            const roomyProjectSender = new SandboxEmailSender(
                {
                    enabled: true,
                    tenantName: 'sandbox',
                    configurationSetName: 'sandbox',
                    fromAddress: 'sender@example.com',
                    dailyTeamCap: '3',
                    dailyRecipientCap: '1',
                },
                teamManager,
                redis,
                limiter
            )
            expect(await roomyProjectSender.claimDailyCaps(7, ['copy@example.com', 'Copy@example.com'])).toEqual({
                type: 'recipient_cap_reached',
                addresses: ['copy@example.com'],
            })
        } finally {
            for (const organizationId of Object.values(organizations)) {
                await deleteKeysWithPrefix(redis, `@posthog/workflows-sandbox-daily/{${organizationId}}`)
            }
        }
    })

    describe('claimAllBuckets', () => {
        it('spends an unanswered claim once when the same EVAL is replayed', async () => {
            const bucket = { key: `${KEY}/claim-replay`, requested: 1, capacity: 2, refillPerSecond: 0 }
            const replayingRedis: RedisV2 = {
                ...redis,
                useClient: async (options, callback) =>
                    redis.useClient(options, async (client) => {
                        const evaluate = client.eval.bind(client)
                        const replay = jest.spyOn(client, 'eval').mockImplementation(async (...args) => {
                            await evaluate(...args)
                            return evaluate(...args)
                        })
                        try {
                            return await callback(client)
                        } finally {
                            replay.mockRestore()
                        }
                    }),
            }
            const replayingLimiter = new RateLimiterService(replayingRedis, { name: 'ses-rate-limiter' })

            expect(await replayingLimiter.claimAllBuckets([bucket])).toMatchObject({ granted: true })
            expect(await limiter.claimAllBuckets([bucket])).toMatchObject({ granted: true })
            expect(await limiter.claimAllBuckets([bucket])).toEqual({ granted: false, deniedIndexes: [0] })
        })

        it('takes no tokens for a claim that reaches Valkey after its caller gave up', async () => {
            const bucket = { key: `${KEY}/claim-too-late`, requested: 1, capacity: 1, refillPerSecond: 0 }
            const issuedAt = Date.now() - 5000
            const lateClock = jest.spyOn(Date, 'now').mockReturnValue(issuedAt)
            try {
                expect(await limiter.claimAllBuckets([bucket])).toEqual({ granted: false, deniedIndexes: null })
            } finally {
                lateClock.mockRestore()
            }

            expect(await limiter.claimAllBuckets([bucket])).toMatchObject({ granted: true })
        })

        it('names every short bucket and spends none of the others', async () => {
            const bucket = (name: string, capacity: number): ClaimRequest => ({
                key: `${KEY}/several-${name}`,
                requested: 1,
                capacity,
                refillPerSecond: 0,
            })
            const [roomy, drained, empty] = [bucket('roomy', 2), bucket('drained', 1), bucket('empty', 0)]
            expect(await limiter.claimAllBuckets([drained])).toMatchObject({ granted: true })

            expect(await limiter.claimAllBuckets([roomy, drained, empty])).toEqual({
                granted: false,
                deniedIndexes: [1, 2],
            })

            expect(await limiter.claimAllBuckets([roomy])).toMatchObject({ granted: true })
            expect(await limiter.claimAllBuckets([roomy])).toMatchObject({ granted: true })
            expect(await limiter.claimAllBuckets([roomy])).toEqual({ granted: false, deniedIndexes: [0] })
        })

        it.each([
            ['no buckets', []],
            ['the same bucket twice', [`${KEY}/twice`, `${KEY}/twice`]],
        ])('refuses a claim with %s', async (_name, keys) => {
            await expect(
                limiter.claimAllBuckets(keys.map((key) => ({ key, requested: 1, capacity: 1, refillPerSecond: 0 })))
            ).rejects.toThrow('every bucket key only once')
        })

        it('fails closed through an optional pool whose Valkey is unreachable', async () => {
            const unreachableValkey = createSesRateLimiterValkeyPool(
                {
                    SES_RATE_LIMITER_VALKEY_HOST: '127.0.0.1',
                    SES_RATE_LIMITER_VALKEY_PORT: 1,
                    SES_RATE_LIMITER_VALKEY_PASSWORD: '',
                    SES_RATE_LIMITER_VALKEY_TLS: false,
                    REDIS_POOL_MIN_SIZE: 1,
                    REDIS_POOL_MAX_SIZE: 2,
                },
                'unreachable-test',
                { optional: true }
            )!
            const unreachable = new RateLimiterService(unreachableValkey, { name: 'sandbox-email' })

            expect(
                await unreachable.claimAllBuckets([
                    { key: `${KEY}/optional-pool`, requested: 1, capacity: 1, refillPerSecond: 0 },
                ])
            ).toEqual({ granted: false, deniedIndexes: null })
        })

        it.each([
            ['a fail-fast pool fails the command at once', { optional: true, failFast: true }, 'rejects'],
            ['an optional pool queues the command until it reconnects', { optional: true }, 'resolves'],
        ] as const)('while the connection drops, %s', async (_name, options, outcome) => {
            const optionalValkey = createSesRateLimiterValkeyPool(
                {
                    SES_RATE_LIMITER_VALKEY_HOST: hub.CDP_REDIS_HOST || '127.0.0.1',
                    SES_RATE_LIMITER_VALKEY_PORT: hub.CDP_REDIS_PORT,
                    SES_RATE_LIMITER_VALKEY_PASSWORD: '',
                    SES_RATE_LIMITER_VALKEY_TLS: false,
                    REDIS_POOL_MIN_SIZE: 1,
                    REDIS_POOL_MAX_SIZE: 1,
                },
                'reconnect-test',
                options
            )!
            expect(await optionalValkey.useClient({ name: 'warm-up' }, (client) => client.ping())).toBe('PONG')

            const duringOutage = optionalValkey.useClient({ name: 'during-outage' }, (client) => {
                ;(client as unknown as { stream: { destroy: () => void } }).stream.destroy()
                return client.get(`${KEY}/during-outage`)
            })

            if (outcome === 'rejects') {
                await expect(duringOutage).rejects.toThrow('enableOfflineQueue')
            } else {
                await expect(duringOutage).resolves.toBeNull()
            }
        })

        it.each([
            ['the email worker wiring', {}],
            ['the email worker wiring without the bounded cap pool', { sandboxEmailCapValkey: undefined }],
        ])(
            'fails a sandbox cap claim closed and returns its claim when Valkey stops answering scripts, through %s',
            async (_case, override) => {
                const stalledValkey: Server = createServer((socket) =>
                    socket.on('data', (data) => {
                        if (!/eval/i.test(data.toString())) {
                            socket.write('$0\r\n\r\n'.repeat(data.toString().match(/^\*\d+\r$/gm)?.length ?? 1))
                        }
                    })
                )
                await new Promise<void>((resolve) => stalledValkey.listen(0, '127.0.0.1', resolve))
                const workerValkeys = createEmailActionValkeys({
                    ...getDefaultCdpConfig(),
                    SES_RATE_LIMITER_VALKEY_HOST: '127.0.0.1',
                    SES_RATE_LIMITER_VALKEY_PORT: (stalledValkey.address() as AddressInfo).port,
                    SES_RATE_LIMITER_VALKEY_PASSWORD: '',
                    SES_RATE_LIMITER_VALKEY_TLS: false,
                    CDP_FREQUENCY_CAP_VALKEY_HOST: '',
                    REDIS_POOL_MIN_SIZE: 0,
                    REDIS_POOL_MAX_SIZE: 1,
                    WORKFLOWS_SANDBOX_SENDER_ENABLED: true,
                })
                const teamManager = {
                    getTeam: () => Promise.resolve({ organization_id: randomUUID() }),
                } as unknown as TeamManager
                const { sandboxEmailCapValkey } = { ...workerValkeys, ...override }
                const sender = new SandboxEmailSender(
                    {
                        enabled: true,
                        tenantName: 'sandbox',
                        configurationSetName: 'sandbox',
                        fromAddress: 'sender@example.com',
                        dailyTeamCap: '1',
                        dailyRecipientCap: '1',
                    },
                    teamManager,
                    redis,
                    createSandboxDailyCapLimiter({ sandboxEmailCapValkey })
                )
                const bucket = { key: `${KEY}/stalled`, requested: 1, capacity: 1, refillPerSecond: 0 }
                try {
                    expect(await sender.claimDailyCaps(1, ['member@example.com'])).toEqual({ type: 'check_failed' })
                    await expect(
                        sender.returnDailyCaps({
                            type: 'granted',
                            claim: {
                                granted: true,
                                claimId: 'stalled-claim',
                                returnBy: Date.now() + 60_000,
                                buckets: [bucket],
                            },
                        })
                    ).resolves.toBeUndefined()
                } finally {
                    await sandboxEmailCapValkey?.useClient({ name: 'test:close-stalled-valkey' }, (client) =>
                        Promise.resolve(client.disconnect())
                    )
                    await new Promise<void>((resolve) => stalledValkey.close(() => resolve()))
                }
            },
            10_000
        )

        it('stops sending commands to a connected Valkey that no longer replies once one command times out', async () => {
            const valkey = stallingValkey()
            await new Promise<void>((resolve) => valkey.server.listen(0, '127.0.0.1', resolve))
            const stalledValkey = createSesRateLimiterValkeyPool(
                {
                    SES_RATE_LIMITER_VALKEY_HOST: '127.0.0.1',
                    SES_RATE_LIMITER_VALKEY_PORT: (valkey.server.address() as AddressInfo).port,
                    SES_RATE_LIMITER_VALKEY_PASSWORD: '',
                    SES_RATE_LIMITER_VALKEY_TLS: false,
                    REDIS_POOL_MIN_SIZE: 1,
                    REDIS_POOL_MAX_SIZE: 1,
                },
                'stall-test',
                { optional: true, failFast: true }
            )!
            let pooled: RedisClient | undefined
            try {
                await stalledValkey.useClient({ name: 'warm-up' }, (client) => {
                    pooled = client
                    return client.set('warm', '1')
                })
                valkey.stall()

                const outcomes: string[] = []
                for (let attempt = 0; attempt < 8; attempt++) {
                    await stalledValkey
                        .useClient({ name: 'claim' }, (client) => client.set('claim', String(attempt)))
                        .then(
                            () => outcomes.push('ok'),
                            (error: Error) => outcomes.push(error.message)
                        )
                }

                expect(outcomes[0]).toBe('Command timed out')
                expect(outcomes).not.toContain('ok')
                expect(valkey.commandsWhileStalled()).toBeLessThanOrEqual(3)
            } finally {
                pooled?.disconnect()
                valkey.sockets.forEach((socket) => socket.destroy())
                await new Promise<void>((resolve) => valkey.server.close(() => resolve()))
            }
        })

        it('reports a limiter error without naming a denied bucket', async () => {
            const unreachable = new RateLimiterService(
                {
                    useClient: () => Promise.reject(new Error('Connection is closed.')),
                    usePipeline: () => Promise.reject(new Error('Connection is closed.')),
                },
                { name: 'ses-rate-limiter' }
            )

            expect(
                await unreachable.claimAllBuckets([
                    { key: `${KEY}/unreachable`, requested: 1, capacity: 1, refillPerSecond: 0 },
                ])
            ).toEqual({ granted: false, deniedIndexes: null })
        })
    })

    describe('returnClaim', () => {
        const grantedClaim = async (bucket: ClaimRequest): Promise<IssuedClaim> => {
            const claim = await limiter.claimAllBuckets([bucket])
            if (!claim.granted) {
                throw new Error('Expected the claim to be granted.')
            }
            return claim
        }

        it('gives a claim back once, even when the return is replayed', async () => {
            const bucket = { key: `${KEY}/return`, requested: 1, capacity: 2, refillPerSecond: 0 }
            const claim = await grantedClaim(bucket)
            await grantedClaim(bucket)

            await limiter.returnClaim(claim)
            await limiter.returnClaim(claim)

            expect(await limiter.claimAllBuckets([bucket])).toMatchObject({ granted: true })
            expect(await limiter.claimAllBuckets([bucket])).toEqual({ granted: false, deniedIndexes: [0] })
        })

        it('gives each bucket of a claim back once, even when the return is replayed', async () => {
            const first = { key: `${KEY}/return-pair-first`, requested: 1, capacity: 2, refillPerSecond: 0 }
            const second = { key: `${KEY}/return-pair-second`, requested: 1, capacity: 3, refillPerSecond: 0 }
            const claim = await limiter.claimAllBuckets([first, second])
            if (!claim.granted) {
                throw new Error('Expected the claim to be granted.')
            }
            expect(await limiter.claimAllBuckets([first, second])).toMatchObject({ granted: true })

            await limiter.returnClaim(claim)
            await limiter.returnClaim(claim)

            expect(await limiter.claimAllBuckets([first, second])).toMatchObject({ granted: true })
            expect(await limiter.claimAllBuckets([first, second])).toEqual({ granted: false, deniedIndexes: [0] })
            expect(await limiter.claimAllBuckets([second])).toMatchObject({ granted: true })
            expect(await limiter.claimAllBuckets([second])).toEqual({ granted: false, deniedIndexes: [0] })
        })

        it('ignores the return of a claim issued longer ago than its window', async () => {
            const bucket = { key: `${KEY}/late-return`, requested: 1, capacity: 1, refillPerSecond: 0 }
            const claim = await grantedClaim(bucket)

            await limiter.returnClaim({ ...claim, returnBy: Date.now() - 1000 })

            expect(await limiter.claimAllBuckets([bucket])).toEqual({ granted: false, deniedIndexes: [0] })
        })

        it('ignores the return of a claim whose bucket could have expired and been drained again', async () => {
            const bucket = {
                key: `${KEY}/short-ttl-return`,
                requested: 1,
                capacity: 1,
                refillPerSecond: 0,
                ttlSeconds: 1,
            }
            const claim = await grantedClaim(bucket)
            await deleteKeysWithPrefix(redis, bucket.key)
            await grantedClaim(bucket)

            await limiter.returnClaim(claim)

            expect(await limiter.claimAllBuckets([bucket])).toEqual({ granted: false, deniedIndexes: [0] })
        })
    })
})
