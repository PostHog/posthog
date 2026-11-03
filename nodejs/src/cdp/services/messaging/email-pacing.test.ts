import { createExampleInvocation } from '~/cdp/_tests/fixtures'

import type { RateLimiterService } from '../rate-limiter/rate-limiter.service'
import {
    WorkflowPacing,
    parseWorkflowEmailRateLimit,
    pickReservedRetryDelayMs,
    pickTokenBucketRetryDelayMs,
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
})
