/**
 * Extracts campaign slug from a coupon URL path.
 * Matches both `/coupons/:campaign` and `/onboarding/coupons/:campaign` patterns.
 *
 * @example
 * parseCouponCampaign('/coupons/lenny') // 'lenny'
 * parseCouponCampaign('/onboarding/coupons/lenny') // 'lenny'
 * parseCouponCampaign('/project/123/onboarding/coupons/lenny') // 'lenny'
 * parseCouponCampaign('/other/path') // null
 */
export function parseCouponCampaign(path: string): string | null {
    const match = path.match(/\/coupons\/([^/?]+)/)
    return match?.[1] ?? null
}
