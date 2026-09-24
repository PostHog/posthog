import { humanFriendlyCurrency } from 'lib/utils/numbers'

import type { CouponCreditStatus } from '~/types'

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

export function formatCouponCreditAmount(creditAmountUsd: string | null | undefined): string | null {
    if (!creditAmountUsd) {
        return null
    }
    const amount = parseFloat(creditAmountUsd)
    if (!Number.isFinite(amount) || amount <= 0) {
        return null
    }
    return humanFriendlyCurrency(amount, Number.isInteger(amount) ? 0 : 2)
}

// While billing still retries the credit sync ("processing"), never say the credit was added.
export function getCouponCreditMessage(
    creditAmountUsd: string | null | undefined,
    creditStatus: CouponCreditStatus | undefined
): string | null {
    const amount = formatCouponCreditAmount(creditAmountUsd)
    if (creditStatus === 'processing') {
        return amount
            ? `${amount} of credit will appear on your account in a few minutes.`
            : 'Your credit will appear on your account in a few minutes.'
    }
    return amount ? `${amount} of credit was added to your organization.` : null
}
