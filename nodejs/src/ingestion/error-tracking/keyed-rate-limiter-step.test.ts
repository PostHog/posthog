import { AppMetricsAggregator } from '~/common/services/app-metrics-aggregator'
import {
    KeyedRateLimit,
    KeyedRateLimitRequest,
    KeyedRateLimiterService,
} from '~/common/services/keyed-rate-limiter.service'

import { isDropResult, isOkResult } from '../pipelines/results'
import { createKeyedRateLimiterStep } from './keyed-rate-limiter-step'

type Input = { teamId: number; key: string | null; cost?: number; bucketOverride?: number }

const mkLimiter = (decisions: Record<string, boolean>): KeyedRateLimiterService =>
    ({
        rateLimitMany: jest.fn((requests: KeyedRateLimitRequest[]) => {
            return Promise.resolve(
                requests.map(({ id }): [string, KeyedRateLimit] => [
                    id,
                    { tokens: decisions[id] ? 0 : 99, isRateLimited: !!decisions[id] },
                ])
            )
        }),
    }) as unknown as KeyedRateLimiterService

const mkAggregator = (): AppMetricsAggregator =>
    ({
        queue: jest.fn(),
    }) as unknown as AppMetricsAggregator

const baseOpts = (overrides: Partial<Parameters<typeof createKeyedRateLimiterStep<Input>>[0]> = {}) => ({
    appSource: 'exceptions',
    getKey: (i: Input) => i.key,
    getCost: (i: Input) => i.cost ?? 1,
    getTeamId: (i: Input) => i.teamId,
    reportingMode: false,
    ...overrides,
})

describe('createKeyedRateLimiterStep', () => {
    it('is a no-op when rateLimiter is undefined', async () => {
        const step = createKeyedRateLimiterStep<Input>(baseOpts({ rateLimiter: undefined }))

        const results = await step([
            { teamId: 1, key: 'a' },
            { teamId: 1, key: 'b' },
        ])

        expect(results).toHaveLength(2)
        expect(results.every(isOkResult)).toBe(true)
    })

    it('returns empty array for empty input', async () => {
        const step = createKeyedRateLimiterStep<Input>(baseOpts({ rateLimiter: mkLimiter({}) }))
        const results = await step([])
        expect(results).toEqual([])
    })

    it('drops rate-limited inputs in enforcing mode', async () => {
        const step = createKeyedRateLimiterStep<Input>(
            baseOpts({
                rateLimiter: mkLimiter({ '1:exceptions:global': true }),
                reportingMode: false,
            })
        )

        const results = await step([
            { teamId: 1, key: '1:exceptions:global' },
            { teamId: 1, key: '1:exceptions:global' },
            { teamId: 2, key: '2:exceptions:global' },
        ])

        expect(isDropResult(results[0])).toBe(true)
        expect(isDropResult(results[1])).toBe(true)
        expect(isOkResult(results[2])).toBe(true)
        if (isDropResult(results[0])) {
            expect(results[0].reason).toBe('rate_limited')
        }
    })

    it('passes through all inputs in reporting mode even when rate limited', async () => {
        const step = createKeyedRateLimiterStep<Input>(
            baseOpts({
                rateLimiter: mkLimiter({ '1:exceptions:global': true }),
                reportingMode: true,
            })
        )

        const results = await step([
            { teamId: 1, key: '1:exceptions:global' },
            { teamId: 1, key: '1:exceptions:global' },
        ])

        expect(results.every(isOkResult)).toBe(true)
    })

    it('passes inputs whose getKey returns null without rate-limiting them', async () => {
        const limiter = mkLimiter({})
        const step = createKeyedRateLimiterStep<Input>(baseOpts({ rateLimiter: limiter }))

        const results = await step([
            { teamId: 1, key: null },
            { teamId: 1, key: null },
        ])

        expect(results.every(isOkResult)).toBe(true)
        expect(limiter.rateLimitMany).not.toHaveBeenCalled()
    })

    it('aggregates cost per unique key in a single Redis call', async () => {
        const limiter = mkLimiter({})
        const step = createKeyedRateLimiterStep<Input>(baseOpts({ rateLimiter: limiter }))

        await step([
            { teamId: 1, key: 'k1', cost: 3 },
            { teamId: 1, key: 'k1', cost: 4 },
            { teamId: 2, key: 'k2', cost: 5 },
        ])

        expect(limiter.rateLimitMany).toHaveBeenCalledTimes(1)
        const calledWith = (limiter.rateLimitMany as jest.Mock).mock.calls[0][0] as KeyedRateLimitRequest[]
        const byId = Object.fromEntries(calledWith.map((req) => [req.id, req.cost]))
        expect(byId).toEqual({ k1: 7, k2: 5 })
    })

    it('forwards per-input bucket config overrides to the limiter (snapshotted from first input per key)', async () => {
        const limiter = mkLimiter({})
        const step = createKeyedRateLimiterStep<Input>(
            baseOpts({
                rateLimiter: limiter,
                getBucketConfig: (i: Input) =>
                    i.bucketOverride !== undefined ? { bucketSize: i.bucketOverride, refillRate: 1 } : {},
            })
        )

        await step([
            { teamId: 1, key: 'k1', bucketOverride: 5 },
            { teamId: 1, key: 'k1', bucketOverride: 999 }, // ignored — first wins
            { teamId: 2, key: 'k2' }, // no override
        ])

        const requests = (limiter.rateLimitMany as jest.Mock).mock.calls[0][0] as KeyedRateLimitRequest[]
        const byId = Object.fromEntries(requests.map((req) => [req.id, req]))
        expect(byId.k1).toMatchObject({ id: 'k1', bucketSize: 5, refillRate: 1 })
        expect(byId.k2.bucketSize).toBeUndefined()
        expect(byId.k2.refillRate).toBeUndefined()
    })

    it('emits one app_metrics2 row per (team, key, outcome) with summed counts', async () => {
        const aggregator = mkAggregator()
        const step = createKeyedRateLimiterStep<Input>(
            baseOpts({
                rateLimiter: mkLimiter({ '1:exceptions:global': true }),
                appMetricsAggregator: aggregator,
                reportingMode: true,
            })
        )

        await step([
            { teamId: 1, key: '1:exceptions:global' },
            { teamId: 1, key: '1:exceptions:global' },
            { teamId: 1, key: '1:exceptions:global' },
            { teamId: 2, key: '2:exceptions:global' },
        ])

        expect(aggregator.queue).toHaveBeenCalledTimes(2)
        expect(aggregator.queue).toHaveBeenCalledWith({
            team_id: 1,
            app_source: 'exceptions',
            app_source_id: '1:exceptions:global',
            metric_kind: 'rate_limiting',
            metric_name: 'rate_limited',
            count: 3,
        })
        expect(aggregator.queue).toHaveBeenCalledWith({
            team_id: 2,
            app_source: 'exceptions',
            app_source_id: '2:exceptions:global',
            metric_kind: 'rate_limiting',
            metric_name: 'allowed',
            count: 1,
        })
    })

    it('does not emit metrics when aggregator is undefined', async () => {
        const limiter = mkLimiter({ a: true })
        const step = createKeyedRateLimiterStep<Input>(
            baseOpts({ rateLimiter: limiter, appMetricsAggregator: undefined })
        )

        await step([{ teamId: 1, key: 'a' }])

        // No throws and limiter was still called.
        expect(limiter.rateLimitMany).toHaveBeenCalled()
    })

    it('uses the configured dropReason', async () => {
        const step = createKeyedRateLimiterStep<Input>(
            baseOpts({
                rateLimiter: mkLimiter({ k: true }),
                reportingMode: false,
                dropReason: 'custom_reason',
            })
        )

        const results = await step([{ teamId: 1, key: 'k' }])
        expect(isDropResult(results[0])).toBe(true)
        if (isDropResult(results[0])) {
            expect(results[0].reason).toBe('custom_reason')
        }
    })
})
