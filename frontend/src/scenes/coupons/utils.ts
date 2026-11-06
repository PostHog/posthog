/**
 * Extracts campaign slug from a coupon URL path.
 * Matches both `/coupons/:campaign` and `/onboarding/coupons/:campaign` patterns.
 * Ignores the query string and hash, so a query value such as `?ref=/coupons/x` doesn't start a coupon onboarding.
 *
 * @example
 * parseCouponCampaign('/coupons/lenny') // 'lenny'
 * parseCouponCampaign('/onboarding/coupons/lenny') // 'lenny'
 * parseCouponCampaign('/project/123/onboarding/coupons/lenny') // 'lenny'
 * parseCouponCampaign('/other/path') // null
 * parseCouponCampaign('/home?ref=/coupons/lenny') // null
 */
export function parseCouponCampaign(path: string): string | null {
    const pathname = path.split(/[?#]/)[0]
    const match = pathname.match(/\/coupons\/([^/]+)/)
    return match?.[1] ?? null
}
