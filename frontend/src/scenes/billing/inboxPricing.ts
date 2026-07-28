import { calculateFreeTier } from 'scenes/billing/billing-utils'

import { BillingProductV2Type } from '~/types'

/**
 * The Inbox billing product — a flat per-PR credit charge for the work agents ship. This is the key
 * billing uses everywhere (it is also the key into `custom_limits_usd`), so surfaces match on it
 * rather than on `usage_key` (the product reports usage under `signals_credits`).
 */
export const INBOX_PRODUCT_TYPE = 'inbox'

export function findInboxProduct(products: BillingProductV2Type[] | undefined): BillingProductV2Type | null {
    return products?.find((product) => product.type === INBOX_PRODUCT_TYPE) ?? null
}

/** Marginal USD price of a single credit, from the first paid tier (falling back to the unit price). */
function perCreditUsd(product: BillingProductV2Type): number | null {
    const paidTier = product.tiers?.find((tier) => parseFloat(tier.unit_amount_usd) > 0)
    if (paidTier) {
        return parseFloat(paidTier.unit_amount_usd)
    }
    return product.unit_amount_usd ? parseFloat(product.unit_amount_usd) : null
}

/** The API's credits → PR divisor. Null means we can't safely talk in PRs. */
export function creditsPerPr(product: BillingProductV2Type | null): number | null {
    return product?.display_divisor && product.display_divisor > 0 ? product.display_divisor : null
}

export function pricePerPrUsd(product: BillingProductV2Type | null): number | null {
    const credits = creditsPerPr(product)
    if (!product || !credits) {
        return null
    }
    const perCredit = perCreditUsd(product)
    return perCredit != null ? perCredit * credits : null
}

/** PRs included each month before anything is charged. */
export function freePrs(product: BillingProductV2Type | null): number {
    const credits = creditsPerPr(product)
    return product && credits ? Math.round(calculateFreeTier(product) / credits) : 0
}
