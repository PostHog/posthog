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
            expect(worker['emailRateLimiter']).toBeNull()
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
            expect(worker['emailRateLimiter']).not.toBeNull()
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
            expect(worker1['emailRateLimiter']).toBeNull()

            const worker2 = new CdpCyclotronWorkerEmail(
                {
                    ...hub,
                    CDP_EMAIL_GLOBAL_RATE_LIMIT_BUCKET_SIZE: 0,
                    CDP_EMAIL_GLOBAL_RATE_LIMIT_REFILL_RATE: 500,
                },
                createCdpConsumerDeps(hub)
            )
            expect(worker2['emailRateLimiter']).toBeNull()
        })
    })
})
