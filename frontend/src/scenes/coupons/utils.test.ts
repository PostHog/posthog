import { parseCouponCampaign } from './utils'

describe('parseCouponCampaign', () => {
    const testCases: [string, string | null][] = [
        // Standard coupon URLs
        ['/coupons/lenny', 'lenny'],
        ['/coupons/my-campaign', 'my-campaign'],
        ['/coupons/campaign_123', 'campaign_123'],

        // Onboarding coupon URLs
        ['/onboarding/coupons/lenny', 'lenny'],
        ['/onboarding/coupons/my-campaign', 'my-campaign'],

        // With project prefix
        ['/project/67/coupons/lenny', 'lenny'],
        ['/project/67/onboarding/coupons/lenny', 'lenny'],

        // With query params
        ['/coupons/lenny?next=/home', 'lenny'],
        ['/onboarding/coupons/lenny?foo=bar', 'lenny'],

        // With trailing slash
        ['/coupons/lenny/', 'lenny'],

        // Non-matching paths
        ['/other/path', null],
        ['/coupon/lenny', null],
        ['/coupons/', null],
        ['/coupons', null],
        ['', null],
    ]

    testCases.forEach(([path, expected]) => {
        it(`parseCouponCampaign("${path}") returns ${expected === null ? 'null' : `"${expected}"`}`, () => {
            expect(parseCouponCampaign(path)).toBe(expected)
        })
    })
})
