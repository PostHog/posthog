import { createMockJobQueue } from '~/tests/helpers/mocks/job-queue.mock'

import { createCdpConsumerDeps } from '~/tests/helpers/cdp'
import { getFirstTeam, resetTestDatabase } from '~/tests/helpers/sql'

import { Hub } from '../../types'
import { closeHub, createHub } from '../../utils/db/hub'
import { createHogExecutionGlobals } from '../_tests/fixtures'
import { EMAIL_RATE_LIMITER_KEY, EMAIL_RATE_LIMITER_NAME } from '../services/messaging/email-rate-limiter.service'
import { CyclotronJobInvocation } from '../types'
import { CdpCyclotronWorkerEmail } from './cdp-cyclotron-worker-email.consumer'

jest.setTimeout(5000)

const KEY_PREFIX = `@posthog-test/${EMAIL_RATE_LIMITER_NAME}/tokens/${EMAIL_RATE_LIMITER_KEY}`

const createEmailInvocation = (id: string, teamId: number): CyclotronJobInvocation =>
    ({
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
        } as any,
        state: {
            globals: createHogExecutionGlobals({}),
            vmState: null,
            timings: [],
            attempts: 0,
        } as any,
    }) as CyclotronJobInvocation

describe('CdpCyclotronWorkerEmail', () => {
    let hub: Hub

    beforeEach(async () => {
        await resetTestDatabase()
        hub = await createHub()
        await getFirstTeam(hub.postgres)
    })

    afterEach(async () => {
        jest.setTimeout(10000)
        await closeHub(hub)
    })

    it('should set queue to email', () => {
        const worker = new CdpCyclotronWorkerEmail(hub, createCdpConsumerDeps(hub), createMockJobQueue())
        expect(worker['queue']).toBe('email')
    })

    it('should extend CdpCyclotronWorkerHogFlow', () => {
        const worker = new CdpCyclotronWorkerEmail(hub, createCdpConsumerDeps(hub), createMockJobQueue())
        expect(worker['name']).toBe('CdpCyclotronWorkerEmail')
    })

    describe('rate limiting', () => {
        const enableRateLimit = (overrides: Partial<Hub> = {}): Hub =>
            ({
                ...hub,
                CDP_EMAIL_VALKEY_HOST: hub.CDP_REDIS_HOST,
                CDP_EMAIL_VALKEY_PORT: hub.CDP_REDIS_PORT,
                CDP_EMAIL_VALKEY_PASSWORD: '',
                CDP_EMAIL_VALKEY_TLS: false,
                CDP_EMAIL_RATE_LIMIT_BUCKET_SIZE: 500,
                CDP_EMAIL_RATE_LIMIT_REFILL_RATE: 500,
                ...overrides,
            }) as Hub

        afterEach(async () => {
            // Flush the rate-limit key so each test starts with a fresh bucket. A
            // throwaway worker gives us a Valkey pool aimed at the same instance the
            // production code would use under these env vars.
            const cleanup = new CdpCyclotronWorkerEmail(
                enableRateLimit(),
                createCdpConsumerDeps(hub),
                createMockJobQueue()
            )
            await cleanup['emailValkey']!.useClient({ name: 'rate-limit-cleanup' }, async (client) => {
                await client.del(KEY_PREFIX)
            })
        })

        it('does not create a rate limiter when the valkey host is unset', () => {
            const worker = new CdpCyclotronWorkerEmail(
                { ...hub, CDP_EMAIL_RATE_LIMIT_BUCKET_SIZE: 500, CDP_EMAIL_RATE_LIMIT_REFILL_RATE: 500 },
                createCdpConsumerDeps(hub),
                createMockJobQueue()
            )

            expect(worker['emailRateLimiter']).toBeNull()
        })

        it('does not create a rate limiter when only one of bucket/refill is set', () => {
            const worker1 = new CdpCyclotronWorkerEmail(
                enableRateLimit({ CDP_EMAIL_RATE_LIMIT_REFILL_RATE: 0 }),
                createCdpConsumerDeps(hub),
                createMockJobQueue()
            )
            expect(worker1['emailRateLimiter']).toBeNull()

            const worker2 = new CdpCyclotronWorkerEmail(
                enableRateLimit({ CDP_EMAIL_RATE_LIMIT_BUCKET_SIZE: 0 }),
                createCdpConsumerDeps(hub),
                createMockJobQueue()
            )
            expect(worker2['emailRateLimiter']).toBeNull()
        })

        it('creates a rate limiter when valkey host + bucket + refill are all set', () => {
            const worker = new CdpCyclotronWorkerEmail(
                enableRateLimit(),
                createCdpConsumerDeps(hub),
                createMockJobQueue()
            )
            expect(worker['emailRateLimiter']).not.toBeNull()
        })

        it('passes the whole batch through when rate limiting is disabled', async () => {
            const worker = new CdpCyclotronWorkerEmail(hub, createCdpConsumerDeps(hub), createMockJobQueue())

            const parentSpy = jest
                .spyOn(Object.getPrototypeOf(Object.getPrototypeOf(worker)), 'processInvocations')
                .mockResolvedValue([{ finished: true }, { finished: true }, { finished: true }] as any)

            const invocations = [
                createEmailInvocation('email-1', 1),
                createEmailInvocation('email-2', 1),
                createEmailInvocation('email-3', 1),
            ]

            const results = await worker.processInvocations(invocations)

            expect(parentSpy).toHaveBeenCalledWith(invocations)
            expect(results).toHaveLength(3)
        })

        it('defers the excess when the batch exceeds the bucket', async () => {
            const worker = new CdpCyclotronWorkerEmail(
                enableRateLimit({ CDP_EMAIL_RATE_LIMIT_BUCKET_SIZE: 2, CDP_EMAIL_RATE_LIMIT_REFILL_RATE: 1 }),
                createCdpConsumerDeps(hub),
                createMockJobQueue()
            )

            const parentSpy = jest
                .spyOn(Object.getPrototypeOf(Object.getPrototypeOf(worker)), 'processInvocations')
                .mockResolvedValue([])

            const invocations = [
                createEmailInvocation('email-1', 1),
                createEmailInvocation('email-2', 1),
                createEmailInvocation('email-3', 1),
            ]

            const results = await worker.processInvocations(invocations)

            // 2 processed, 1 deferred (rescheduled with queueScheduledAt)
            expect(parentSpy).toHaveBeenCalledWith(invocations.slice(0, 2))
            const deferred = results.filter((r) => !r.finished && r.invocation.queueScheduledAt)
            expect(deferred).toHaveLength(1)
        })

        it('defers the entire batch when the bucket is empty', async () => {
            const worker = new CdpCyclotronWorkerEmail(
                enableRateLimit({ CDP_EMAIL_RATE_LIMIT_BUCKET_SIZE: 1, CDP_EMAIL_RATE_LIMIT_REFILL_RATE: 0.0001 }),
                createCdpConsumerDeps(hub),
                createMockJobQueue()
            )

            jest.spyOn(Object.getPrototypeOf(Object.getPrototypeOf(worker)), 'processInvocations').mockResolvedValue([])

            // Drain the single token.
            await worker.processInvocations([createEmailInvocation('warmup', 1)])

            const results = await worker.processInvocations([
                createEmailInvocation('email-1', 1),
                createEmailInvocation('email-2', 1),
            ])

            const deferred = results.filter((r) => !r.finished && r.invocation.queueScheduledAt)
            expect(deferred.length).toBeGreaterThanOrEqual(1)
        })

        it('staggers deferred reschedules with jitter to avoid thundering herd', async () => {
            const worker = new CdpCyclotronWorkerEmail(
                enableRateLimit({ CDP_EMAIL_RATE_LIMIT_BUCKET_SIZE: 0.0001, CDP_EMAIL_RATE_LIMIT_REFILL_RATE: 0.0001 }),
                createCdpConsumerDeps(hub),
                createMockJobQueue()
            )

            jest.spyOn(Object.getPrototypeOf(Object.getPrototypeOf(worker)), 'processInvocations').mockResolvedValue([])

            const invocations = Array.from({ length: 20 }, (_, i) => createEmailInvocation(`email-${i}`, 1))
            const results = await worker.processInvocations(invocations)

            const deferred = results.filter((r) => !r.finished && r.invocation.queueScheduledAt)
            expect(deferred.length).toBeGreaterThan(0)

            const delays = new Set(deferred.map((r) => r.invocation.queueScheduledAt!.toMillis()))
            // Jitter range is 0–200ms — across 20 invocations we expect at least a few distinct delays.
            expect(delays.size).toBeGreaterThan(1)
        })

        it('fails open and processes the whole batch when the rate limiter throws', async () => {
            const worker = new CdpCyclotronWorkerEmail(
                enableRateLimit(),
                createCdpConsumerDeps(hub),
                createMockJobQueue()
            )

            const parentSpy = jest
                .spyOn(Object.getPrototypeOf(Object.getPrototypeOf(worker)), 'processInvocations')
                .mockResolvedValue([{ finished: true }, { finished: true }] as any)
            jest.spyOn(worker['emailRateLimiter']!, 'decide').mockRejectedValue(new Error('valkey down'))

            const invocations = [createEmailInvocation('email-1', 1), createEmailInvocation('email-2', 1)]
            const results = await worker.processInvocations(invocations)

            expect(parentSpy).toHaveBeenCalledWith(invocations)
            expect(results).toHaveLength(2)
        })
    })
})
