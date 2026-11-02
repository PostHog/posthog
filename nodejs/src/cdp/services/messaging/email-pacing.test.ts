import {
    parseTeamEmailCapMode,
    parseTierCaps,
    parseWorkflowEmailRateLimit,
    pickReservedRetryDelayMs,
    pickThrottleRetryDelayMs,
    pickTokenBucketRetryDelayMs,
    teamEmailCapBuckets,
} from './email-pacing'

describe('email pacing policies', () => {
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
        it('keeps tier order while ignoring empty entries', () => {
            expect(parseTierCaps(' 50, ,200,600, ')).toEqual([50, 200, 600])
        })

        it.each([undefined, '', '50,invalid,200', '50,0,200', '50,-1,200', '50,Infinity,200'])(
            'disables the whole table for %s',
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
        afterEach(() => {
            jest.restoreAllMocks()
        })

        it.each([
            [0, 500],
            [0.9999, 999],
        ])('uses a short SES throttle delay at jitter %s', (random, expected) => {
            jest.spyOn(Math, 'random').mockReturnValue(random)
            expect(pickThrottleRetryDelayMs()).toBe(expected)
        })

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
})
