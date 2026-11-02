import { createExampleInvocation } from '~/cdp/_tests/fixtures'

import type { TeamWorkflowsConfigService } from '../managers/team-workflows-config.service'
import type { RateLimiterService } from '../rate-limiter/rate-limiter.service'
import {
    TeamEmailCapConfig,
    TeamSendingCap,
    WorkflowPacing,
    parseTeamEmailCapMode,
    parseTierCaps,
    parseWorkflowEmailRateLimit,
    pickReservedRetryDelayMs,
    pickTokenBucketRetryDelayMs,
    teamEmailCapBuckets,
} from './email-pacing'

describe('email pacing policies', () => {
    afterEach(() => {
        jest.restoreAllMocks()
    })

    describe('parseTeamEmailCapMode', () => {
        it.each([
            [undefined, 'off'],
            ['off', 'off'],
            ['enforce', 'enforce'],
            [' SHADOW ', 'shadow'],
            ['enabled', 'off'],
        ])('reads %s as %s', (value, expected) => {
            expect(parseTeamEmailCapMode(value)).toBe(expected)
        })
    })

    describe('parseTierCaps', () => {
        it('reads a table with spaces and a trailing comma', () => {
            expect(parseTierCaps(' 50, 200,600, ')).toEqual([50, 200, 600])
        })

        it.each([undefined, '', '50,invalid,200', '50,0,200', '50,-1,200', '50,Infinity,200'])(
            'drops the whole table for %s, so the default caps apply',
            (value) => {
                expect(parseTierCaps(value)).toEqual([])
            }
        )
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
            [2, 0, 1000],
            [2, 0.9999, 1999],
            [0.1, 0.5, 15000],
            [0.001, 0, 300000],
            [0.001, 0.9999, 599970],
        ])('bounds the unreserved token cadence at refill %s and jitter %s', (refillPerSecond, random, expected) => {
            jest.spyOn(Math, 'random').mockReturnValue(random)
            expect(pickTokenBucketRetryDelayMs(refillPerSecond)).toBe(expected)
        })

        it.each([
            [null, 2, false, 0.5, 1500],
            [null, 0.001, false, 0.5, 450000],
            [null, 2, true, 0.5, 1500],
            [250, 2, true, 0.5, 250],
            [5400000, 2, true, 0.5, 5400000],
            [250, 2, false, 0.5, 1500],
            [3600000, 2, false, 0.5, 5400000],
        ])(
            'parks horizon %s at refill %s, reserved %s and jitter %s',
            (retryAfterMs, refillPerSecond, reserved, random, expected) => {
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
        const limiter = { claimAllOrNothingPair: jest.fn(), claimUpTo: jest.fn() }
        const tiers = { getEmailSendingTier: jest.fn() }
        const invocation = createExampleInvocation({ team_id: 7 })
        const capFor = (config: TeamEmailCapConfig): TeamSendingCap =>
            new TeamSendingCap(
                limiter as unknown as RateLimiterService,
                tiers as unknown as TeamWorkflowsConfigService,
                config
            )
        const enforce = capFor({
            teamEmailCapMode: 'enforce',
            teamEmailTierHourlyCaps: [5, 50],
            teamEmailTierDailyCaps: [20, 200],
        })

        beforeEach(() => {
            limiter.claimAllOrNothingPair.mockReset()
            limiter.claimUpTo.mockReset()
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

        it('charges one token per recipient, but never more than the smaller bucket holds', async () => {
            limiter.claimAllOrNothingPair.mockResolvedValue({
                granted: true,
                deniedIndex: null,
                retryAfterMs: null,
                reserved: false,
            })

            await enforce.claim(invocation, false, 3)
            await enforce.claim(invocation, false, 500)

            expect(limiter.claimAllOrNothingPair.mock.calls.map((call) => call[1])).toEqual([3, 5])
        })

        it('parks a denied send and names the full bucket', async () => {
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

        it('paces a limiter failure on the daily bucket and names no cap', async () => {
            jest.spyOn(Math, 'random').mockReturnValue(0)
            limiter.claimAllOrNothingPair.mockResolvedValue({
                granted: false,
                deniedIndex: null,
                retryAfterMs: null,
                reserved: false,
            })
            const cap = capFor({
                teamEmailCapMode: 'enforce',
                teamEmailTierHourlyCaps: [36000],
                teamEmailTierDailyCaps: [8640],
            })

            expect(await cap.claim(invocation, false)).toEqual({
                retryDelayMs: 10000,
                logMessage:
                    "Could not check this project's email sending limit, so this email is waiting. Retrying in 10s. No action is needed on your side.",
            })
        })

        it('drains both buckets in shadow mode but never delays the send', async () => {
            limiter.claimUpTo.mockResolvedValue(0)

            expect(
                await capFor({
                    teamEmailCapMode: 'shadow',
                    teamEmailTierHourlyCaps: [5],
                    teamEmailTierDailyCaps: [20],
                }).claim(invocation, false)
            ).toBeNull()
            expect(limiter.claimUpTo).toHaveBeenCalledTimes(2)
            expect(limiter.claimAllOrNothingPair).not.toHaveBeenCalled()
        })

        it.each([
            ['the cap is off', capFor({ teamEmailCapMode: 'off' }), false, 0],
            ['the send is a test', capFor({ teamEmailCapMode: 'enforce' }), true, 0],
            ['the tier lookup found no tier', capFor({ teamEmailCapMode: 'enforce' }), false, null],
        ])('lets a send through without claiming when %s', async (_name, cap, isTest, tier) => {
            tiers.getEmailSendingTier.mockResolvedValue(tier)

            expect(await cap.claim(invocation, isTest)).toBeNull()
            expect(limiter.claimAllOrNothingPair).not.toHaveBeenCalled()
            expect(limiter.claimUpTo).not.toHaveBeenCalled()
        })
    })
})
