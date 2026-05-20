// Pre-Cymbal rate limiter spec generation is exercised here as a unit test rather
// than through the full pipeline. The aim is to verify key derivation, bucket sizing,
// and toggle behaviour; the rate-limiter step itself is covered by
// keyed-rate-limiter-step.test.ts and the full pipeline integration is covered by
// error-tracking-pipeline.test.ts.
import { KeyedRateLimiterService } from '~/common/services/keyed-rate-limiter.service'

import { ErrorTrackingConsumer } from './error-tracking-consumer'
import { PreCymbalRateLimiterInput } from './error-tracking-pipeline'
import { KeyedRateLimiterStepOptions } from './keyed-rate-limiter-step'

type SpecConsumerOverrides = Partial<{
    rateLimiterReportingMode: boolean
    rateLimiterPerHashEnabled: boolean
    rateLimiterPerHashBucketSize: number
    rateLimiterPerHashBucketMinutes: number
}>

interface SpecConsumerLike {
    config: SpecConsumerOverrides
    rateLimiter: KeyedRateLimiterService | undefined
    rateLimiterAppMetricsAggregator: undefined
    buildPreCymbalRateLimiterSpecs(): KeyedRateLimiterStepOptions<PreCymbalRateLimiterInput>[]
}

const mkSpecConsumer = (overrides: SpecConsumerOverrides = {}): SpecConsumerLike => {
    // ErrorTrackingConsumer's constructor wires up Kafka/Redis. We're only here to
    // exercise spec generation, so bypass the constructor and assign the fields the
    // private builder reads.
    const c = Object.create(ErrorTrackingConsumer.prototype) as unknown as SpecConsumerLike
    c.config = {
        rateLimiterReportingMode: false,
        rateLimiterPerHashEnabled: false,
        rateLimiterPerHashBucketSize: 100,
        rateLimiterPerHashBucketMinutes: 5,
        ...overrides,
    }
    c.rateLimiter = { rateLimitGrouped: jest.fn() } as unknown as KeyedRateLimiterService
    c.rateLimiterAppMetricsAggregator = undefined
    return c
}

const buildSpecs = (overrides: SpecConsumerOverrides = {}): KeyedRateLimiterStepOptions<PreCymbalRateLimiterInput>[] =>
    mkSpecConsumer(overrides).buildPreCymbalRateLimiterSpecs()

const mkInput = (overrides: Partial<{ type: string; value: string; teamId: number }> = {}) =>
    ({
        team: { id: overrides.teamId ?? 1 },
        event: {
            properties: {
                $exception_list: [{ type: overrides.type ?? 'TypeError', value: overrides.value ?? 'undefined' }],
            },
        },
        errorTrackingSettings: null,
    }) as unknown as PreCymbalRateLimiterInput

const mkInputRaw = (event: { properties: Record<string, unknown> }, teamId = 1) =>
    ({ team: { id: teamId }, event, errorTrackingSettings: null }) as unknown as PreCymbalRateLimiterInput

describe('buildPreCymbalRateLimiterSpecs', () => {
    it('returns an empty list when the rate limiter is disabled, even if per-hash is enabled', () => {
        const c = mkSpecConsumer({ rateLimiterPerHashEnabled: true })
        c.rateLimiter = undefined
        expect(c.buildPreCymbalRateLimiterSpecs()).toEqual([])
    })

    it('emits only the team-global spec when per-hash is disabled', () => {
        const specs = buildSpecs({ rateLimiterPerHashEnabled: false })
        expect(specs).toHaveLength(1)
        expect(specs[0].dropReason).toBe('rate_limited:team_global')
    })

    it('appends the per-hash spec when enabled', () => {
        const specs = buildSpecs({ rateLimiterPerHashEnabled: true })
        expect(specs).toHaveLength(2)
        expect(specs[1].dropReason).toBe('rate_limited:per_hash')
        expect(specs[1].appSource).toBe('exceptions')
    })

    describe('per-hash key derivation', () => {
        const perHashSpec = () => buildSpecs({ rateLimiterPerHashEnabled: true })[1]

        it('is stable for identical (team, type, value)', () => {
            const spec = perHashSpec()
            const a = spec.getKey(mkInput({ teamId: 7, type: 'TypeError', value: 'undefined is not a function' }))
            const b = spec.getKey(mkInput({ teamId: 7, type: 'TypeError', value: 'undefined is not a function' }))
            expect(a).toBe(b)
            expect(a).toMatch(/^7:exceptions:hash:[0-9a-f]{16}$/)
        })

        it('differs when the message changes', () => {
            const spec = perHashSpec()
            const a = spec.getKey(mkInput({ type: 'TypeError', value: 'undefined' }))
            const b = spec.getKey(mkInput({ type: 'TypeError', value: 'different' }))
            expect(a).not.toBe(b)
        })

        it('is namespaced by team_id so identical exceptions across teams do not share a bucket', () => {
            const spec = perHashSpec()
            const team7 = spec.getKey(mkInput({ teamId: 7, type: 'TypeError', value: 'undefined' }))
            const team9 = spec.getKey(mkInput({ teamId: 9, type: 'TypeError', value: 'undefined' }))
            expect(team7).not.toBe(team9)
        })

        it('returns null when both type and value are missing (skip rate-limiting)', () => {
            const spec = perHashSpec()
            expect(spec.getKey(mkInputRaw({ properties: {} }))).toBeNull()
            expect(spec.getKey(mkInputRaw({ properties: { $exception_list: [{}] } }))).toBeNull()
        })

        it('hashes type-only and value-only inputs without collision', () => {
            const spec = perHashSpec()
            const typeOnly = spec.getKey(mkInputRaw({ properties: { $exception_list: [{ type: 'TypeError' }] } }))
            const valueOnly = spec.getKey(mkInputRaw({ properties: { $exception_list: [{ value: 'oops' }] } }))
            expect(typeOnly).toMatch(/^1:exceptions:hash:[0-9a-f]{16}$/)
            expect(valueOnly).toMatch(/^1:exceptions:hash:[0-9a-f]{16}$/)
            expect(typeOnly).not.toBe(valueOnly)
        })
    })

    it('derives bucket config from bucket size and minutes (refillRate = N / (M * 60))', () => {
        const spec = buildSpecs({
            rateLimiterPerHashEnabled: true,
            rateLimiterPerHashBucketSize: 100,
            rateLimiterPerHashBucketMinutes: 5,
        })[1]
        expect(spec.getBucketConfig!(mkInput())).toEqual({ bucketSize: 100, refillRate: 100 / 300 })
    })

    it('propagates reportingMode to the per-hash spec', () => {
        const spec = buildSpecs({ rateLimiterPerHashEnabled: true, rateLimiterReportingMode: true })[1]
        expect(spec.reportingMode).toBe(true)
    })
})
