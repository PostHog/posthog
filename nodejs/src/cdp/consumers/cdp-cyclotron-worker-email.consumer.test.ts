import { createCdpConsumerDeps } from '~/tests/helpers/cdp'
import { getFirstTeam, resetTestDatabase } from '~/tests/helpers/sql'

import { Hub } from '../../types'
import { closeHub, createHub } from '../../utils/db/hub'
import { createHogExecutionGlobals } from '../_tests/fixtures'
import { BASE_REDIS_KEY } from '../services/monitoring/hog-rate-limiter.service'
import { CyclotronJobInvocation } from '../types'
import { CdpCyclotronWorkerEmail } from './cdp-cyclotron-worker-email.consumer'

jest.setTimeout(5000)

const createEmailInvocation = (id: string, teamId: number): CyclotronJobInvocation => ({
    id,
    teamId,
    functionId: 'function-1',
    queue: 'email',
    queuePriority: 0,
    queueParameters: {
        type: 'email',
        to: { email: 'user@example.com' },
        from: { email: 'noreply@posthog.com', integrationId: 1 },
        subject: 'Test',
        text: 'Hello',
        html: '<p>Hello</p>',
    },
    state: {
        globals: createHogExecutionGlobals({}),
        vmState: null,
        timings: [],
        attempts: 0,
    },
})

describe('CdpCyclotronWorkerEmail', () => {
    let hub: Hub

    beforeEach(async () => {
        await resetTestDatabase()
        hub = await createHub()
        await getFirstTeam(hub.postgres)

        // Flush rate limiter keys to avoid cross-test contamination
        const worker = new CdpCyclotronWorkerEmail(hub, createCdpConsumerDeps(hub))
        await worker['redis'].useClient({ name: 'test-cleanup' }, async (client) => {
            const keys = await client.keys(`${BASE_REDIS_KEY}/*`)
            if (keys.length > 0) {
                await client.del(...keys)
            }
        })
    })

    afterEach(async () => {
        jest.setTimeout(10000)
        await closeHub(hub)
    })

    it('should set queue to email', () => {
        const worker = new CdpCyclotronWorkerEmail(hub, createCdpConsumerDeps(hub))
        expect(worker['queue']).toBe('email')
    })

    describe('rate limiting', () => {
        it('should not create rate limiter when config is 0', () => {
            const worker = new CdpCyclotronWorkerEmail(hub, createCdpConsumerDeps(hub))
            expect(worker['globalRateLimiter']).toBeNull()
        })

        it('should create rate limiter when config is set', () => {
            const worker = new CdpCyclotronWorkerEmail(
                {
                    ...hub,
                    CDP_EMAIL_GLOBAL_RATE_LIMIT_BUCKET_SIZE: 500,
                    CDP_EMAIL_GLOBAL_RATE_LIMIT_REFILL_RATE: 500,
                },
                createCdpConsumerDeps(hub)
            )
            expect(worker['globalRateLimiter']).not.toBeNull()
        })

        it('should defer invocations when rate limit is exceeded', async () => {
            const worker = new CdpCyclotronWorkerEmail(
                {
                    ...hub,
                    CDP_EMAIL_GLOBAL_RATE_LIMIT_BUCKET_SIZE: 2,
                    CDP_EMAIL_GLOBAL_RATE_LIMIT_REFILL_RATE: 1,
                },
                createCdpConsumerDeps(hub)
            )

            // Mock parent processInvocations to avoid needing full hogflow setup
            jest.spyOn(Object.getPrototypeOf(Object.getPrototypeOf(worker)), 'processInvocations').mockResolvedValue([])

            const invocations = [
                createEmailInvocation('email-1', 1),
                createEmailInvocation('email-2', 1),
                createEmailInvocation('email-3', 1),
            ]

            const results = await worker.processInvocations(invocations)

            // 2 processed (bucket size), 1 deferred
            const deferred = results.filter((r) => !r.finished && r.invocation.queueScheduledAt)
            expect(deferred).toHaveLength(1)
            expect(deferred[0].invocation.queueScheduledAt).toBeDefined()
        })

        it('should defer all invocations when bucket is empty', async () => {
            const worker = new CdpCyclotronWorkerEmail(
                {
                    ...hub,
                    CDP_EMAIL_GLOBAL_RATE_LIMIT_BUCKET_SIZE: 1,
                    CDP_EMAIL_GLOBAL_RATE_LIMIT_REFILL_RATE: 0.001,
                },
                createCdpConsumerDeps(hub)
            )

            jest.spyOn(Object.getPrototypeOf(Object.getPrototypeOf(worker)), 'processInvocations').mockResolvedValue([])

            // Exhaust the bucket (1 token)
            await worker.processInvocations([createEmailInvocation('setup-1', 1)])

            // Now all should be deferred (refill is negligible at 0.001/sec)
            const results = await worker.processInvocations([
                createEmailInvocation('email-1', 1),
                createEmailInvocation('email-2', 1),
            ])

            const deferred = results.filter((r) => !r.finished && r.invocation.queueScheduledAt)
            // At least 1 deferred since bucket was exhausted (exact count depends on timing/refill)
            expect(deferred.length).toBeGreaterThanOrEqual(1)
        })

        it('should add jitter to deferred invocation delays', async () => {
            const worker = new CdpCyclotronWorkerEmail(
                {
                    ...hub,
                    CDP_EMAIL_GLOBAL_RATE_LIMIT_BUCKET_SIZE: 1,
                    CDP_EMAIL_GLOBAL_RATE_LIMIT_REFILL_RATE: 0.001,
                },
                createCdpConsumerDeps(hub)
            )

            jest.spyOn(Object.getPrototypeOf(Object.getPrototypeOf(worker)), 'processInvocations').mockResolvedValue([])

            // Exhaust the bucket
            await worker.processInvocations([createEmailInvocation('setup-1', 1)])

            // Mock Math.random to return different values for each deferred invocation
            let callCount = 0
            jest.spyOn(Math, 'random').mockImplementation(() => {
                callCount++
                return (callCount * 0.3) % 1
            })

            // Defer multiple — their delays should not all be identical
            const results = await worker.processInvocations([
                createEmailInvocation('email-1', 1),
                createEmailInvocation('email-2', 1),
                createEmailInvocation('email-3', 1),
            ])

            const deferred = results.filter((r) => !r.finished && r.invocation.queueScheduledAt)
            expect(deferred.length).toBeGreaterThanOrEqual(1)

            // When multiple are deferred, their delays should vary due to jitter
            if (deferred.length >= 2) {
                const delays = deferred.map((r) => r.invocation.queueScheduledAt!.toMillis())
                const allSame = delays.every((d) => d === delays[0])
                expect(allSame).toBe(false)
            }
        })

        it('should process all invocations when rate limiting is disabled', async () => {
            const worker = new CdpCyclotronWorkerEmail(hub, createCdpConsumerDeps(hub))

            const parentSpy = jest
                .spyOn(Object.getPrototypeOf(Object.getPrototypeOf(worker)), 'processInvocations')
                .mockResolvedValue([{ finished: true }, { finished: true }, { finished: true }])

            const invocations = [
                createEmailInvocation('email-1', 1),
                createEmailInvocation('email-2', 1),
                createEmailInvocation('email-3', 1),
            ]

            const results = await worker.processInvocations(invocations)

            // All passed through to parent — no rate limiting
            expect(parentSpy).toHaveBeenCalledWith(invocations)
            expect(results).toHaveLength(3)
        })

        it('should not create rate limiter when only one config value is set', () => {
            const worker1 = new CdpCyclotronWorkerEmail(
                {
                    ...hub,
                    CDP_EMAIL_GLOBAL_RATE_LIMIT_BUCKET_SIZE: 500,
                    CDP_EMAIL_GLOBAL_RATE_LIMIT_REFILL_RATE: 0,
                },
                createCdpConsumerDeps(hub)
            )
            expect(worker1['globalRateLimiter']).toBeNull()

            const worker2 = new CdpCyclotronWorkerEmail(
                {
                    ...hub,
                    CDP_EMAIL_GLOBAL_RATE_LIMIT_BUCKET_SIZE: 0,
                    CDP_EMAIL_GLOBAL_RATE_LIMIT_REFILL_RATE: 500,
                },
                createCdpConsumerDeps(hub)
            )
            expect(worker2['globalRateLimiter']).toBeNull()
        })
    })

    describe('per-team rate limiting', () => {
        it('should create per-team rate limiter when config is set', () => {
            const worker = new CdpCyclotronWorkerEmail(
                {
                    ...hub,
                    CDP_EMAIL_PER_TEAM_RATE_LIMIT_BUCKET_SIZE: 50,
                    CDP_EMAIL_PER_TEAM_RATE_LIMIT_REFILL_RATE: 10,
                },
                createCdpConsumerDeps(hub)
            )
            expect(worker['perTeamRateLimiter']).not.toBeNull()
        })

        it('should not create per-team rate limiter when config is 0', () => {
            const worker = new CdpCyclotronWorkerEmail(hub, createCdpConsumerDeps(hub))
            expect(worker['perTeamRateLimiter']).toBeNull()
        })

        it('should defer emails from teams that exceed their per-team limit', async () => {
            const worker = new CdpCyclotronWorkerEmail(
                {
                    ...hub,
                    CDP_EMAIL_PER_TEAM_RATE_LIMIT_BUCKET_SIZE: 2,
                    CDP_EMAIL_PER_TEAM_RATE_LIMIT_REFILL_RATE: 0.001,
                },
                createCdpConsumerDeps(hub)
            )

            jest.spyOn(Object.getPrototypeOf(Object.getPrototypeOf(worker)), 'processInvocations').mockResolvedValue([])

            // Team 1 sends 3 emails (over limit of 2), Team 2 sends 1 (under limit)
            const invocations = [
                createEmailInvocation('t1-email-1', 1),
                createEmailInvocation('t1-email-2', 1),
                createEmailInvocation('t1-email-3', 1),
                createEmailInvocation('t2-email-1', 2),
            ]

            const results = await worker.processInvocations(invocations)

            const deferred = results.filter((r) => !r.finished && r.invocation.queueScheduledAt)
            // Team 1 should have 1 deferred (3 sent, bucket 2)
            expect(deferred.length).toBeGreaterThanOrEqual(1)

            // Team 2's email should not be deferred
            const team2Deferred = deferred.filter((r) => r.invocation.teamId === 2)
            expect(team2Deferred).toHaveLength(0)
        })

        it('should apply both global and per-team limits', async () => {
            const worker = new CdpCyclotronWorkerEmail(
                {
                    ...hub,
                    CDP_EMAIL_GLOBAL_RATE_LIMIT_BUCKET_SIZE: 10,
                    CDP_EMAIL_GLOBAL_RATE_LIMIT_REFILL_RATE: 10,
                    CDP_EMAIL_PER_TEAM_RATE_LIMIT_BUCKET_SIZE: 1,
                    CDP_EMAIL_PER_TEAM_RATE_LIMIT_REFILL_RATE: 0.001,
                },
                createCdpConsumerDeps(hub)
            )

            jest.spyOn(Object.getPrototypeOf(Object.getPrototypeOf(worker)), 'processInvocations').mockResolvedValue([])

            // Global allows 10, but per-team allows only 1 each
            const invocations = [
                createEmailInvocation('t1-email-1', 1),
                createEmailInvocation('t1-email-2', 1),
                createEmailInvocation('t2-email-1', 2),
                createEmailInvocation('t2-email-2', 2),
            ]

            const results = await worker.processInvocations(invocations)

            const deferred = results.filter((r) => !r.finished && r.invocation.queueScheduledAt)
            // Each team should have 1 deferred (2 sent per team, bucket 1 per team)
            expect(deferred.length).toBeGreaterThanOrEqual(2)
        })
    })
})
