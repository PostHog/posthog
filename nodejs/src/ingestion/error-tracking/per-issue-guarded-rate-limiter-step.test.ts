import { AppMetricsAggregator } from '~/common/services/app-metrics-aggregator'

import { isDropResult, isOkResult } from '../pipelines/results'
import { createPerIssueGuardedRateLimiterStep } from './per-issue-guarded-rate-limiter-step'
import {
    GuardedStatus,
    PerIssueGuardedRateLimiterService,
    PerIssueGuardedResult,
} from './per-issue-guarded-rate-limiter.service'

type Input = { teamId: number; sig: string | null; cost?: number }

const mkLimiter = (statuses: Record<string, GuardedStatus>): PerIssueGuardedRateLimiterService => {
    const bucketKey = (teamId: number, sig: string) => `tok/${teamId}:exceptions:issue:${sig}`
    return {
        bucketKey,
        rateLimit: jest.fn((requests) => {
            const out = new Map<string, PerIssueGuardedResult>()
            for (const req of requests) {
                const key = bucketKey(req.teamId, req.sig)
                const status = statuses[key] ?? 'allowed'
                // Mirror real server behavior: when limited, the bucket was drained, so
                // tokensBefore reads as 0 and the client-side fan-out (budget < cost) will
                // mark inputs as limited. Tripped/fallback also return 0 tokens.
                const tokensBefore = status === 'allowed' ? 100 : 0
                const tokens = status === 'allowed' ? 99 : status === 'limited' ? -1 : 0
                out.set(key, {
                    tokensBefore,
                    tokens,
                    isRateLimited: status === 'limited',
                    status,
                })
            }
            return Promise.resolve(out)
        }),
    } as unknown as PerIssueGuardedRateLimiterService
}

const mkAggregator = (): AppMetricsAggregator => ({ queue: jest.fn() }) as unknown as AppMetricsAggregator

const baseOpts = (overrides: Partial<Parameters<typeof createPerIssueGuardedRateLimiterStep<Input>>[0]> = {}) => ({
    appSource: 'exceptions',
    getGuardKey: (i: Input) => (i.sig === null ? null : { teamId: i.teamId, sig: i.sig }),
    getCost: (i: Input) => i.cost ?? 1,
    getBucketConfig: () => ({ bucketSize: 100, refillRate: 1 }),
    reportingMode: false,
    ...overrides,
})

describe('createPerIssueGuardedRateLimiterStep', () => {
    it('is a no-op when rateLimiter is undefined', async () => {
        const step = createPerIssueGuardedRateLimiterStep<Input>(baseOpts({ rateLimiter: undefined }))

        const results = await step([
            { teamId: 1, sig: 'a' },
            { teamId: 1, sig: 'b' },
        ])

        expect(results).toHaveLength(2)
        expect(results.every(isOkResult)).toBe(true)
    })

    it('skips inputs whose getGuardKey returns null', async () => {
        const limiter = mkLimiter({})
        const step = createPerIssueGuardedRateLimiterStep<Input>(baseOpts({ rateLimiter: limiter }))

        const results = await step([
            { teamId: 1, sig: null },
            { teamId: 1, sig: 'a' },
        ])

        expect(results.every(isOkResult)).toBe(true)
        // Only the non-null sig was passed to the limiter.
        expect((limiter.rateLimit as jest.Mock).mock.calls[0][0]).toEqual([
            expect.objectContaining({ teamId: 1, sig: 'a' }),
        ])
    })

    it('passes allowed inputs through and drops limited inputs in enforcing mode', async () => {
        const limiter = mkLimiter({ 'tok/1:exceptions:issue:noisy': 'limited' })
        const step = createPerIssueGuardedRateLimiterStep<Input>(
            baseOpts({ rateLimiter: limiter, reportingMode: false })
        )

        const results = await step([
            { teamId: 1, sig: 'quiet' },
            { teamId: 1, sig: 'noisy' },
        ])

        expect(isOkResult(results[0])).toBe(true)
        expect(isDropResult(results[1])).toBe(true)
        if (isDropResult(results[1])) {
            expect(results[1].reason).toBe('rate_limited:per_issue_guarded')
        }
    })

    it('passes through limited inputs in reporting mode', async () => {
        const limiter = mkLimiter({ 'tok/1:exceptions:issue:noisy': 'limited' })
        const step = createPerIssueGuardedRateLimiterStep<Input>(
            baseOpts({ rateLimiter: limiter, reportingMode: true })
        )

        const results = await step([{ teamId: 1, sig: 'noisy' }])
        expect(results.every(isOkResult)).toBe(true)
    })

    it('passes tripped / fallback inputs through (defers to team-global limiter)', async () => {
        const limiter = mkLimiter({
            'tok/1:exceptions:issue:trippy': 'tripped',
            'tok/2:exceptions:issue:downstream': 'fallback',
        })
        const step = createPerIssueGuardedRateLimiterStep<Input>(baseOpts({ rateLimiter: limiter }))

        const results = await step([
            { teamId: 1, sig: 'trippy' },
            { teamId: 2, sig: 'downstream' },
        ])

        expect(results.every(isOkResult)).toBe(true)
    })

    it('rate-limits inputs that drain a shared sig bucket in a single batch', async () => {
        // bucketSize 2, cost 1 per input: third input in the same sig group must be limited.
        const limiter = mkLimiter({})
        const step = createPerIssueGuardedRateLimiterStep<Input>(
            baseOpts({
                rateLimiter: limiter,
                getBucketConfig: () => ({ bucketSize: 2, refillRate: 0 }),
            })
        )

        // The mock limiter returns `allowed` with tokensBefore=100, so to exercise the
        // client-side fan-out we override the mock for this test:
        ;(limiter.rateLimit as jest.Mock).mockImplementationOnce((requests) => {
            const out = new Map<string, PerIssueGuardedResult>()
            for (const req of requests) {
                out.set(limiter.bucketKey(req.teamId, req.sig), {
                    tokensBefore: 2,
                    tokens: 2 - req.cost,
                    isRateLimited: false,
                    status: 'allowed',
                })
            }
            return Promise.resolve(out)
        })

        const results = await step([
            { teamId: 1, sig: 'shared' },
            { teamId: 1, sig: 'shared' },
            { teamId: 1, sig: 'shared' },
        ])

        expect(isOkResult(results[0])).toBe(true)
        expect(isOkResult(results[1])).toBe(true)
        expect(isDropResult(results[2])).toBe(true)
    })

    it('emits app metrics when an aggregator is provided', async () => {
        const aggregator = mkAggregator()
        const limiter = mkLimiter({ 'tok/1:exceptions:issue:noisy': 'limited' })
        const step = createPerIssueGuardedRateLimiterStep<Input>(
            baseOpts({ rateLimiter: limiter, appMetricsAggregator: aggregator })
        )

        await step([
            { teamId: 1, sig: 'noisy' },
            { teamId: 1, sig: 'noisy' },
            { teamId: 1, sig: 'quiet' },
        ])

        const queued = (aggregator.queue as jest.Mock).mock.calls.map((args) => args[0])
        expect(queued).toEqual(
            expect.arrayContaining([
                expect.objectContaining({ team_id: 1, metric_name: 'limited', count: 2 }),
                expect.objectContaining({ team_id: 1, metric_name: 'allowed', count: 1 }),
            ])
        )
    })
})
