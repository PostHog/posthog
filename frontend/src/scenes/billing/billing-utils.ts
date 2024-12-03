import { dayjs } from 'lib/dayjs'

import { BillingProductV2Type, BillingTierType, BillingType } from '~/types'

export const summarizeUsage = (usage: number | null): string => {
    if (usage === null) {
        return ''
    } else if (usage < 1000) {
        return `${usage}`
    } else if (Math.round(usage / 1000) < 1000) {
        return `${Math.round(usage / 1000)} thousand`
    }
    return `${Math.round(usage / 1000000)} million`
}

export const projectUsage = (usage: number | undefined, period: BillingType['billing_period']): number | undefined => {
    if (typeof usage === 'undefined') {
        return usage
    }
    if (!period) {
        return usage
    }

    const timeSoFar = dayjs().diff(period.current_period_start, 'hours')

    // If less than 6 hours have passed, we don't have enough data to project
    if (timeSoFar <= 6) {
        return usage
    }
    const timeTotal = period.current_period_end.diff(period.current_period_start, 'hours')

    return Math.round((usage / timeSoFar) * timeTotal)
}

export const convertUsageToAmount = (
    usage: number,
    productAndAddonTiers: BillingTierType[][],
    percentDiscount?: number
): string => {
    if (!productAndAddonTiers) {
        return ''
    }
    let remainingUsage = usage
    let amount = 0
    let previousTier: BillingTierType | undefined = undefined

    const tiers = productAndAddonTiers[0].map((tier, index) => {
        const allAddonsTiers = productAndAddonTiers.slice(1)
        let totalAmount = parseFloat(tier.unit_amount_usd)
        let flatFee = parseFloat(tier.flat_amount_usd || '0')
        for (const addonTiers of allAddonsTiers) {
            totalAmount += parseFloat(addonTiers[index].unit_amount_usd)
            flatFee += parseFloat(addonTiers[index].flat_amount_usd || '0')
        }
        return {
            ...tier,
            unit_amount_usd: totalAmount.toString(),
            flat_amount_usd: flatFee.toString(),
        }
    })

    for (const tier of tiers) {
        if (remainingUsage <= 0) {
            break
        }

        const tierUsageMax = tier.up_to ? tier.up_to - (previousTier?.up_to || 0) : Infinity
        const amountFloatUsd = parseFloat(tier.unit_amount_usd)
        const tierFlatFee = parseFloat(tier.flat_amount_usd || '0')
        const usageThisTier = Math.min(remainingUsage, tierUsageMax)
        remainingUsage -= usageThisTier
        amount += amountFloatUsd * usageThisTier
        if (tierFlatFee) {
            amount += tierFlatFee
        }
        previousTier = tier
    }

    // remove discount from total price
    if (percentDiscount) {
        amount = amount * (1 - percentDiscount / 100)
    }

    return amount.toFixed(2)
}

export const convertAmountToUsage = (
    amount: string,
    productAndAddonTiers: BillingTierType[][],
    discountPercent?: number
): number => {
    if (!amount) {
        return 0
    }
    if (!productAndAddonTiers || productAndAddonTiers.length === 0) {
        return 0
    }

    const tiers = productAndAddonTiers[0].map((tier, index) => {
        const allAddonsTiers = productAndAddonTiers.slice(1)
        let totalAmount = parseFloat(tier.unit_amount_usd)
        let flatFee = parseFloat(tier.flat_amount_usd || '0')
        for (const addonTiers of allAddonsTiers) {
            totalAmount += parseFloat(addonTiers[index].unit_amount_usd)
            flatFee += parseFloat(addonTiers[index].flat_amount_usd || '0')
        }
        return {
            ...tier,
            unit_amount_usd: totalAmount.toString(),
            flat_amount_usd: flatFee.toString(),
        }
    })

    let remainingAmount = parseFloat(amount)
    let usage = 0
    let previousTier: BillingTierType | undefined = undefined

    if (remainingAmount === 0) {
        if (parseFloat(tiers[0].unit_amount_usd) === 0) {
            return tiers[0].up_to || 0
        }
        return 0
    }

    // consider discounts so user knows what unit amount they'll be throttled at
    if (discountPercent) {
        remainingAmount = remainingAmount / (1 - discountPercent / 100)
    }

    const allTiersZero = tiers.every((tier) => !parseFloat(tier.unit_amount_usd))

    if (allTiersZero) {
        // Free plan - usage cannot be calculated
        return tiers[0].up_to || 0
    }

    for (const tier of tiers) {
        if (remainingAmount <= 0) {
            break
        }

        const tierUsageMax = tier.up_to ? tier.up_to - (previousTier?.up_to || 0) : Infinity
        const amountFloatUsd = parseFloat(tier.unit_amount_usd)
        const tierFlatFee = parseFloat(tier.flat_amount_usd || '0')
        const usageThisTier = Math.min(remainingAmount / amountFloatUsd, tierUsageMax)

        usage += usageThisTier
        remainingAmount -= amountFloatUsd * usageThisTier
        if (tierFlatFee) {
            remainingAmount -= tierFlatFee
        }
        previousTier = tier
    }

    return Math.round(usage)
}

export const getUpgradeProductLink = ({
    product,
    redirectPath,
    includeAddons = true,
}: {
    product: BillingProductV2Type
    redirectPath?: string
    includeAddons: boolean
}): string => {
    let url = '/api/billing/activate?'
    if (redirectPath) {
        url += `redirect_path=${redirectPath}&`
    }

    url += `products=all_products:&intent_product=${product.type},`

    if (includeAddons && product.addons?.length) {
        for (const addon of product.addons) {
            if (
                // TODO: this breaks if we support multiple plans per addon due to just grabbing the first plan
                addon.plans?.[0]?.plan_key &&
                !addon.inclusion_only
            ) {
                url += `${addon.type}:${addon.plans[0].plan_key},`
            }
        }
    }
    // remove the trailing comma that will be at the end of the url
    url = url.slice(0, -1)
    return url
}

export const convertLargeNumberToWords = (
    // The number to convert
    num: number | null,
    // The previous tier's number
    previousNum: number | null,
    // Whether we will be showing multiple tiers (to denote the first tier with 'first')
    multipleTiers: boolean = false,
    // The product type (to denote the unit)
    productType: BillingProductV2Type['type'] | null = null
): string => {
    if (num === null && previousNum) {
        return `${convertLargeNumberToWords(previousNum, null)} +`
    }
    if (num === null) {
        return ''
    }

    let denominator = 1
    if (num >= 1000000) {
        denominator = 1000000
    } else if (num >= 1000) {
        denominator = 1000
    }

    let prevDenominator = 1
    if (previousNum && previousNum >= 1000000) {
        prevDenominator = 1000000
    } else if (previousNum && previousNum >= 1000) {
        prevDenominator = 1000
    }

    return `${previousNum ? `${((previousNum + 1) / prevDenominator).toFixed(0)}-` : multipleTiers ? 'First ' : ''}${(
        num / denominator
    ).toFixed(0)}${denominator === 1000000 ? ' million' : denominator === 1000 ? 'k' : ''}${
        !previousNum && multipleTiers ? ` ${productType}s/mo` : ''
    }`
}

export const getProration = ({
    timeRemainingInSeconds,
    timeTotalInSeconds,
    amountUsd,
    hasActiveSubscription,
}: {
    timeRemainingInSeconds: number
    timeTotalInSeconds: number
    amountUsd?: string | null
    hasActiveSubscription?: boolean
}): {
    isProrated: boolean
    prorationAmount: string
} => {
    if (timeTotalInSeconds === 0) {
        return {
            isProrated: false,
            prorationAmount: '0.00',
        }
    }

    const prorationAmount = amountUsd ? parseInt(amountUsd) * (timeRemainingInSeconds / timeTotalInSeconds) : 0

    return {
        isProrated: hasActiveSubscription && amountUsd ? prorationAmount !== parseInt(amountUsd || '') : false,
        prorationAmount: prorationAmount.toFixed(2),
    }
}

export const getProrationMessage = (prorationAmount: string, unitAmountUsd: string | null): string => {
    return `Pay ~$${prorationAmount} today (prorated) and $${parseInt(unitAmountUsd || '0')} every month thereafter.`
}
