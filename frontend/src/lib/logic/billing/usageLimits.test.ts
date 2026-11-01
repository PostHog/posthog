import { OrganizationMembershipLevel } from 'lib/constants'

import {
    buildUsageLimitApproachingMessage,
    buildUsageLimitReachedMessage,
    formatProductNames,
    getUsageLimitConsequence,
    isUsageApproachingLimit,
    isUsageAtOrOverLimit,
} from './usageLimits'

describe('usage limit thresholds', () => {
    it('treats exactly 100% usage as at the limit', () => {
        expect(isUsageAtOrOverLimit(null)).toBe(false)
        expect(isUsageAtOrOverLimit(undefined)).toBe(false)
        expect(isUsageAtOrOverLimit(0.99)).toBe(false)
        expect(isUsageAtOrOverLimit(1)).toBe(true)
        expect(isUsageAtOrOverLimit(1.01)).toBe(true)
    })

    it('only treats usage below 100% as approaching the limit', () => {
        expect(isUsageApproachingLimit(0.8, 0.8)).toBe(false)
        expect(isUsageApproachingLimit(0.81, 0.8)).toBe(true)
        expect(isUsageApproachingLimit(1, 0.8)).toBe(false)
        expect(isUsageApproachingLimit(1.01, 0.8)).toBe(false)
    })
})

describe('formatProductNames', () => {
    it('should return empty string for empty array', () => {
        expect(formatProductNames([])).toEqual('')
    })

    it('should return single product name as-is', () => {
        expect(formatProductNames(['Session replay'])).toEqual('Session replay')
    })

    it('should join two products with "and"', () => {
        expect(formatProductNames(['Session replay', 'Feature flags & Experiments'])).toEqual(
            'Session replay and Feature flags & Experiments'
        )
    })

    it('should join three or more products with commas and "and"', () => {
        expect(formatProductNames(['Product analytics', 'Session replay', 'Feature flags & Experiments'])).toEqual(
            'Product analytics, Session replay and Feature flags & Experiments'
        )
    })
})

describe('getUsageLimitConsequence', () => {
    it.each(['Data warehouse', 'Sources'])('should return the sync consequence for %s', (name) => {
        expect(getUsageLimitConsequence(name)).toEqual('data will not be synced')
    })

    it('should return specific message for Feature flags & Experiments', () => {
        expect(getUsageLimitConsequence('Feature flags & Experiments')).toEqual('feature flags will not evaluate')
    })

    it('should return specific message for PostHog AI', () => {
        expect(getUsageLimitConsequence('PostHog AI')).toEqual('PostHog AI will be unavailable')
    })

    it('should return specific message for the self-driving inbox', () => {
        expect(getUsageLimitConsequence('Self-driving inbox')).toEqual('self-driving agents will be paused')
    })

    it('should return generic message for other products', () => {
        expect(getUsageLimitConsequence('Session replay')).toEqual('data loss may occur')
        expect(getUsageLimitConsequence('Product analytics')).toEqual('data loss may occur')
        expect(getUsageLimitConsequence('Surveys')).toEqual('data loss may occur')
    })
})

describe('buildUsageLimitReachedMessage', () => {
    it('should return empty strings for empty array', () => {
        expect(buildUsageLimitReachedMessage([])).toEqual({ title: '', message: '' })
    })

    it('should build message for single subscribed product', () => {
        const result = buildUsageLimitReachedMessage([{ name: 'Session replay', subscribed: true }])
        expect(result.title).toEqual('Usage limit reached')
        expect(result.message).toEqual(
            'You have reached the usage limit for Session replay. Please increase your billing limit or data loss may occur.'
        )
    })

    it('should build message for single unsubscribed product', () => {
        const result = buildUsageLimitReachedMessage([{ name: 'Session replay', subscribed: false }])
        expect(result.message).toContain('upgrade your plan')
    })

    it.each(['Data warehouse', 'Sources'])('should explain stopped syncing for %s at its usage limit', (name) => {
        const result = buildUsageLimitReachedMessage([{ type: 'data_warehouse', name, subscribed: true }])
        expect(result.message).toEqual(
            `You have reached the usage limit for ${name}. Please increase your billing limit or data will not be synced.`
        )
    })

    it('should build message for multiple products with unique consequences', () => {
        const result = buildUsageLimitReachedMessage([
            { name: 'Session replay', subscribed: true },
            { name: 'Feature flags & Experiments', subscribed: true },
        ])
        expect(result.title).toEqual('Usage limits reached')
        expect(result.message).toEqual(
            'You have reached the usage limit for Session replay and Feature flags & Experiments. Please increase your billing limit or data loss may occur and feature flags will not evaluate.'
        )
    })

    it('should build message for PostHog AI with specific consequence', () => {
        const result = buildUsageLimitReachedMessage([{ name: 'PostHog AI', subscribed: true }])
        expect(result.title).toEqual('Usage limit reached')
        expect(result.message).toEqual(
            'You have reached the usage limit for PostHog AI. Please increase your billing limit or PostHog AI will be unavailable.'
        )
    })

    it('should name the self-driving inbox by its app name, not its billing name', () => {
        const result = buildUsageLimitReachedMessage([{ type: 'inbox', name: 'Inbox', subscribed: true }])
        expect(result.title).toEqual('Usage limit reached')
        expect(result.message).toEqual(
            'You have reached the usage limit for Self-driving inbox. Please increase your billing limit or self-driving agents will be paused.'
        )
    })

    it('should build message for PostHog AI with other products', () => {
        const result = buildUsageLimitReachedMessage([
            { name: 'PostHog AI', subscribed: true },
            { name: 'Session replay', subscribed: true },
        ])
        expect(result.title).toEqual('Usage limits reached')
        expect(result.message).toEqual(
            'You have reached the usage limit for PostHog AI and Session replay. Please increase your billing limit or PostHog AI will be unavailable and data loss may occur.'
        )
    })

    it('should deduplicate consequences for products with same consequence', () => {
        const result = buildUsageLimitReachedMessage([
            { name: 'Session replay', subscribed: true },
            { name: 'Product analytics', subscribed: true },
        ])
        expect(result.message).toEqual(
            'You have reached the usage limit for Session replay and Product analytics. Please increase your billing limit or data loss may occur.'
        )
    })

    it('should use upgrade message when any product is not subscribed', () => {
        const result = buildUsageLimitReachedMessage([
            { name: 'Session replay', subscribed: true },
            { name: 'Feature flags & Experiments', subscribed: false },
        ])
        expect(result.message).toContain('upgrade your plan')
    })

    it.each([
        {
            hasBillingAccess: true,
            subscribed: true,
            expected: 'increase your billing limit',
        },
        {
            hasBillingAccess: true,
            subscribed: false,
            expected: 'upgrade your plan',
        },
        {
            hasBillingAccess: false,
            subscribed: true,
            expected: 'ask an organization admin to increase the billing limit',
        },
        {
            hasBillingAccess: false,
            subscribed: false,
            expected: 'ask an organization admin to upgrade the plan',
        },
    ])(
        'should use "$expected" when hasBillingAccess=$hasBillingAccess and subscribed=$subscribed',
        ({ hasBillingAccess, subscribed, expected }) => {
            const result = buildUsageLimitReachedMessage([{ name: 'Session replay', subscribed }], hasBillingAccess)
            expect(result.message).toContain(expected)
        }
    )

    it('should say "owner" when minimumBillingAccessLevel is Owner and user has no billing access', () => {
        const result = buildUsageLimitReachedMessage(
            [{ name: 'Session replay', subscribed: true }],
            false,
            OrganizationMembershipLevel.Owner
        )
        expect(result.message).toContain('ask an organization owner')
    })

    it('should default to admin message when hasBillingAccess is not provided', () => {
        const result = buildUsageLimitReachedMessage([{ name: 'Session replay', subscribed: true }])
        expect(result.message).toContain('increase your billing limit')
    })
})

describe('buildUsageLimitApproachingMessage', () => {
    it('should return empty strings for empty array', () => {
        expect(buildUsageLimitApproachingMessage([])).toEqual({ title: '', message: '' })
    })

    it('should build message for single product', () => {
        const result = buildUsageLimitApproachingMessage([
            { name: 'Session replay', percentage_usage: 0.9, usage_key: 'recordings' },
        ])
        expect(result.title).toEqual('You will soon hit your usage limit')
        expect(result.message).toEqual('You have currently used 90% of your Session replay allocation.')
    })

    it('should build message for multiple products', () => {
        const result = buildUsageLimitApproachingMessage([
            { name: 'Session replay', percentage_usage: 0.9, usage_key: 'recordings' },
            { name: 'Feature flags & Experiments', percentage_usage: 0.87, usage_key: 'feature_flag_requests' },
        ])
        expect(result.title).toEqual('You will soon hit your usage limits')
        expect(result.message).toEqual(
            'You are approaching your usage limits: 90% of your Session replay allocation, 87% of your Feature flags & Experiments allocation.'
        )
    })

    it.each([
        { name: 'Session replay', usage_key: undefined, expected: 'Session replay allocation' },
        { name: '', usage_key: 'signals_credits', expected: 'signals_credits allocation' },
        { name: '', usage_key: undefined, expected: 'usage allocation' },
    ])('should resolve label to "$expected" (name="$name", usage_key=$usage_key)', ({ name, usage_key, expected }) => {
        const result = buildUsageLimitApproachingMessage([{ name, percentage_usage: 0.9, usage_key }])
        expect(result.message).toContain(expected)
    })

    it('should format percentage with up to 2 decimal places', () => {
        const result = buildUsageLimitApproachingMessage([
            { name: 'Session replay', percentage_usage: 0.8567, usage_key: 'recordings' },
        ])
        expect(result.message).toContain('85.67%')
    })

    it.each([
        {
            hasBillingAccess: true,
            expectedSuffix: false,
        },
        {
            hasBillingAccess: false,
            expectedSuffix: true,
        },
    ])(
        'should include admin contact message when hasBillingAccess=$hasBillingAccess',
        ({ hasBillingAccess, expectedSuffix }) => {
            const result = buildUsageLimitApproachingMessage(
                [{ name: 'Session replay', percentage_usage: 0.9, usage_key: 'recordings' }],
                hasBillingAccess
            )
            if (expectedSuffix) {
                expect(result.message).toContain('Please ask an organization admin to increase the billing limit.')
            } else {
                expect(result.message).not.toContain('organization admin')
            }
        }
    )

    it('should say "owner" when minimumBillingAccessLevel is Owner and user has no billing access', () => {
        const result = buildUsageLimitApproachingMessage(
            [{ name: 'Session replay', percentage_usage: 0.9, usage_key: 'recordings' }],
            false,
            OrganizationMembershipLevel.Owner
        )
        expect(result.message).toContain('ask an organization owner')
    })

    it('should default to no admin suffix when hasBillingAccess is not provided', () => {
        const result = buildUsageLimitApproachingMessage([
            { name: 'Session replay', percentage_usage: 0.9, usage_key: 'recordings' },
        ])
        expect(result.message).not.toContain('organization admin')
    })
})
