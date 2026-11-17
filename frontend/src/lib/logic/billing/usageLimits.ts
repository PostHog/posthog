import { OrganizationMembershipLevel } from 'lib/constants'
import { membershipLevelToName } from 'lib/utils/permissioning'
import { capitalizeFirstLetter } from 'lib/utils/strings'

import { billingProductDisplayName } from './billingProductDisplayName'

export const isUsageAtOrOverLimit = (percentageUsage: number | null | undefined): boolean => {
    return (percentageUsage ?? 0) >= 1
}

export const isUsageApproachingLimit = (percentageUsage: number | null | undefined, threshold: number): boolean => {
    return (percentageUsage ?? 0) > threshold && !isUsageAtOrOverLimit(percentageUsage)
}

/**
 * Build a human-readable list of product names (e.g., "A, B and C")
 */
export function formatProductNames(names: string[]): string {
    if (names.length === 0) {
        return ''
    }
    if (names.length === 1) {
        return names[0]
    }
    return names.slice(0, -1).join(', ') + ' and ' + names[names.length - 1]
}

/**
 * Get the consequence message for a product when it reaches its usage limit
 */
export function getUsageLimitConsequence(productName: string): string {
    if (productName === 'Data warehouse' || productName === 'Sources') {
        return 'data will not be synced'
    }
    if (productName === 'Feature flags & Experiments') {
        return 'feature flags will not evaluate'
    }
    if (productName === 'PostHog AI') {
        return 'PostHog AI will be unavailable'
    }
    if (productName === 'Self-driving inbox') {
        return 'self-driving agents will be paused'
    }
    return 'data loss may occur'
}

/**
 * Build a consolidated message for products that have reached their usage limits
 */
export function buildUsageLimitReachedMessage(
    products: Array<{ type?: string | null; name: string; subscribed: boolean | null }>,
    hasBillingAccess: boolean = true,
    minimumBillingAccessLevel: OrganizationMembershipLevel = OrganizationMembershipLevel.Admin,
    selfServeBillingNotice: string | null = null
): {
    title: string
    message: string
} {
    if (products.length === 0) {
        return { title: '', message: '' }
    }

    const productNames = products.map(billingProductDisplayName)
    const allSubscribed = products.every((p) => p.subscribed === true)

    // Build consequence message, deduplicating common consequences
    const consequences = [...new Set(productNames.map(getUsageLimitConsequence))]

    const productListText = formatProductNames(productNames)
    const consequenceText = consequences.join(' and ')
    const title = products.length === 1 ? 'Usage limit reached' : 'Usage limits reached'

    if (selfServeBillingNotice && !allSubscribed) {
        return {
            title,
            message: `You have reached the usage limit for ${productListText}. ${capitalizeFirstLetter(consequenceText)}. ${selfServeBillingNotice}`,
        }
    }

    let actionText: string
    if (hasBillingAccess) {
        actionText = allSubscribed ? 'increase your billing limit' : 'upgrade your plan'
    } else {
        const roleName = membershipLevelToName.get(minimumBillingAccessLevel)
        actionText = allSubscribed
            ? `ask an organization ${roleName} to increase the billing limit`
            : `ask an organization ${roleName} to upgrade the plan`
    }

    return {
        title,
        message: `You have reached the usage limit for ${productListText}. Please ${actionText} or ${consequenceText}.`,
    }
}

/**
 * Build a consolidated message for products approaching their usage limits
 */
export function buildUsageLimitApproachingMessage(
    products: Array<{
        type?: string | null
        name: string
        percentage_usage: number
        usage_key?: string | null
    }>,
    hasBillingAccess: boolean = true,
    minimumBillingAccessLevel: OrganizationMembershipLevel = OrganizationMembershipLevel.Admin
): { title: string; message: string } {
    if (products.length === 0) {
        return { title: '', message: '' }
    }

    const usageDetails = products.map((p) => {
        const percentage = parseFloat((p.percentage_usage * 100).toFixed(2))
        const productName = (p.name && billingProductDisplayName(p)) || p.usage_key?.toLowerCase() || 'usage'
        return `${percentage}% of your ${productName} allocation`
    })

    const roleName = membershipLevelToName.get(minimumBillingAccessLevel)
    const adminSuffix = hasBillingAccess ? '' : ` Please ask an organization ${roleName} to increase the billing limit.`

    const message =
        products.length === 1
            ? `You have currently used ${usageDetails[0]}.${adminSuffix}`
            : `You are approaching your usage limits: ${usageDetails.join(', ')}.${adminSuffix}`

    return {
        title: products.length === 1 ? 'You will soon hit your usage limit' : 'You will soon hit your usage limits',
        message,
    }
}
