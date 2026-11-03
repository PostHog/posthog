import { createExampleInvocation } from '~/cdp/_tests/fixtures'

import type { TeamWorkflowsConfigService } from '../managers/team-workflows-config.service'
import type { RateLimiterService } from '../rate-limiter/rate-limiter.service'
import {
    TeamSendingCap,
    WorkflowPacing,
    parseWorkflowEmailRateLimit,
    pickReservedRetryDelayMs,
    pickTokenBucketRetryDelayMs,
    teamEmailCapBuckets,
} from './email-pacing'

describe('email pacing policies', () => {
    afterEach(() => {
        jest.restoreAllMocks()
    })

    describe('parseWorkflowEmailRateLimit', () => {
        it.each(['minute', 'hour'])('reads a %s limit from workflow metadata', (period) => {
            expect(parseWorkflowEmailRateLimit({ email_sending_rate_limit: { count: 6, period } })).toEqual({
                count: 6,
                period,
            })
        })

        it.each([
            undefined,
            {},
            { count: 0, period: 'minute' },
            { count: 1.5, period: 'hour' },
            { count: 6, period: 'day' },
        ])('ignores an absent or unusable rate limit %j', (value) => {
            expect(parseWorkflowEmailRateLimit({ email_sending_rate_limit: value })).toBeNull()
        })
    })

    it('builds hourly and daily buckets in one team hash slot with TTLs beyond their refill periods', () => {
        expect(teamEmailCapBuckets(42, 3600, 43200)).toEqual([
            {
                name: 'hour',
                key: '@posthog/team-email-rate-hour/{42}',
                capacity: 3600,
                refillPerSecond: 1,
                ttlSeconds: 21600,
                label: '3,600 emails per hour',
            },
            {
                name: 'day',
                key: '@posthog/team-email-rate-day/{42}',
                capacity: 43200,
                refillPerSecond: 0.5,
                ttlSeconds: 259200,
                label: '43,200 emails per day',
            },
        ])
    })

    describe('retry delays', () => {
        it.each([
            { refillPerSecond: 2, random: 0, expected: 1000 },
            { refillPerSecond: 2, random: 0.9999, expected: 1999 },
            { refillPerSecond: 0.1, random: 0.5, expected: 15000 },
            { refillPerSecond: 0.001, random: 0, expected: 300000 },
            { refillPerSecond: 0.001, random: 0.9999, expected: 599970 },
        ])(
            'bounds the unreserved token cadence at refill $refillPerSecond and jitter $random',
            ({ refillPerSecond, random, expected }) => {
                jest.spyOn(Math, 'random').mockReturnValue(random)
                expect(pickTokenBucketRetryDelayMs(refillPerSecond)).toBe(expected)
            }
        )

        it.each([
            { retryAfterMs: null, refillPerSecond: 2, reserved: false, random: 0.5, expected: 1500 },
            { retryAfterMs: null, refillPerSecond: 0.001, reserved: false, random: 0.5, expected: 450000 },
            { retryAfterMs: null, refillPerSecond: 2, reserved: true, random: 0.5, expected: 1500 },
            { retryAfterMs: 250, refillPerSecond: 2, reserved: true, random: 0.5, expected: 250 },
            { retryAfterMs: 5400000, refillPerSecond: 2, reserved: true, random: 0.5, expected: 5400000 },
            { retryAfterMs: 250, refillPerSecond: 2, reserved: false, random: 0.5, expected: 1500 },
            { retryAfterMs: 3600000, refillPerSecond: 2, reserved: false, random: 0.5, expected: 5400000 },
        ])(
            'parks horizon $retryAfterMs at refill $refillPerSecond, reserved $reserved and jitter $random',
            ({ retryAfterMs, refillPerSecond, reserved, random, expected }) => {
                jest.spyOn(Math, 'random').mockReturnValue(random)
                expect(pickReservedRetryDelayMs(retryAfterMs, refillPerSecond, reserved)).toBe(expected)
            }
        )
    })

    describe('WorkflowPacing.claim', () => {
        const limiter = { claimOrReserve: jest.fn() }
        const pacing = new WorkflowPacing(limiter as unknown as RateLimiterService)
        const invocation = createExampleInvocation({
            team_id: 7,
            metadata: { email_sending_rate_limit: { count: 60, period: 'minute' } },
        })

        beforeEach(() => {
            limiter.claimOrReserve.mockReset()
        })

        it('lets a send through when the workflow bucket grants a token', async () => {
            limiter.claimOrReserve.mockResolvedValue({ granted: 1, retryAfterMs: null, reserved: false })

            expect(await pacing.claim(invocation, false)).toBeNull()
            expect(limiter.claimOrReserve).toHaveBeenCalledWith(
                expect.objectContaining({ requested: 1, capacity: 1, refillPerSecond: 1 }),
                expect.any(Number)
            )
        })

        it('parks a denied send on its reserved slot and names the workflow limit', async () => {
            limiter.claimOrReserve.mockResolvedValue({ granted: 0, retryAfterMs: 4000, reserved: true })

            expect(await pacing.claim(invocation, false)).toEqual({
                retryDelayMs: 4000,
                logMessage: 'Sending rate limit reached (60 emails per minute); retrying this email in 4s',
            })
        })

        it('never claims for a test send', async () => {
            expect(await pacing.claim(invocation, true)).toBeNull()
            expect(limiter.claimOrReserve).not.toHaveBeenCalled()
        })
    })

    describe('TeamSendingCap.claim', () => {
        const limiter = { claimAllOrNothingPair: jest.fn() }
        const tiers = { getEmailSendingTier: jest.fn() }
        const invocation = createExampleInvocation({ team_id: 7 })
        const enforce = new TeamSendingCap(
            limiter as unknown as RateLimiterService,
            tiers as unknown as TeamWorkflowsConfigService,
            { teamEmailCapMode: 'enforce', teamEmailTierHourlyCaps: [5, 50], teamEmailTierDailyCaps: [20, 200] }
        )

        beforeEach(() => {
            limiter.claimAllOrNothingPair.mockReset()
            tiers.getEmailSendingTier.mockReset().mockResolvedValue(0)
        })

        it.each([
            ['a tier above the table', 9, 50, 200],
            ['a negative tier', -1, 5, 20],
        ])('caps %s at the nearest tier in the table', async (_name, tier, hourly, daily) => {
            tiers.getEmailSendingTier.mockResolvedValue(tier)
            limiter.claimAllOrNothingPair.mockResolvedValue({
                granted: true,
                deniedIndex: null,
                retryAfterMs: null,
                reserved: false,
            })

            expect(await enforce.claim(invocation, false)).toBeNull()
            const [buckets] = limiter.claimAllOrNothingPair.mock.calls[0]
            expect(buckets.map((bucket: { capacity: number }) => bucket.capacity)).toEqual([hourly, daily])
        })

        it('parks a send the daily bucket denies and names the daily cap', async () => {
            limiter.claimAllOrNothingPair.mockResolvedValue({
                granted: false,
                deniedIndex: 1,
                retryAfterMs: 4000,
                reserved: true,
            })

            expect(await enforce.claim(invocation, false)).toEqual({
                retryDelayMs: 4000,
                logMessage:
                    'This project reached its email sending limit of 20 emails per day. Retrying this email in 4s. The limit rises as the project builds a clean sending history.',
            })
        })
    })
})
