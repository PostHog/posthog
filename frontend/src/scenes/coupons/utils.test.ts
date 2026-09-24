import { formatCouponCreditAmount, parseCouponCampaign } from './utils'

describe('coupon utils', () => {
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

    describe('formatCouponCreditAmount', () => {
        it.each([
            ['50.00', '$50'],
            ['30.00', '$30'],
            ['12.50', '$12.50'],
            ['1500.00', '$1,500'],
            ['0.00', null],
            [null, null],
            [undefined, null],
            ['', null],
        ])('formatCouponCreditAmount(%p) returns %p', (amount, expected) => {
            expect(formatCouponCreditAmount(amount)).toBe(expected)
        })
    })
})
