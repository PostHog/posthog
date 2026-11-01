import { FEATURE_FLAGS, OrganizationMembershipLevel } from 'lib/constants'
import type { FeatureFlagsSet } from 'lib/logic/featureFlagLogic'

/**
 * Returns the minimum membership level required to access billing.
 * When ownerOnlyBilling is true (via the owner-only-billing feature flag), only org owners can access billing.
 */
export function getMinimumBillingAccessLevel(ownerOnlyBilling: boolean): OrganizationMembershipLevel {
    return ownerOnlyBilling ? OrganizationMembershipLevel.Owner : OrganizationMembershipLevel.Admin
}

/**
 * Determines if the user has sufficient permissions to access billing based on their org membership level.
 */
export function canAccessBilling(membershipLevel: number | null | undefined, ownerOnlyBilling: boolean): boolean {
    if (!membershipLevel) {
        return false
    }
    return membershipLevel >= getMinimumBillingAccessLevel(ownerOnlyBilling)
}

/** Whether the member-level read grant for usage and spend is in effect. */
export function isMemberUsageSpendReadAccessEnabled(featureFlags: FeatureFlagsSet): boolean {
    return !!featureFlags[FEATURE_FLAGS.MEMBER_BILLING_USAGE_SPEND_READ_ACCESS]
}

/**
 * Returns the minimum membership level required for read-only access to the billing usage/spend tabs.
 * The member-billing-usage-spend-read-access feature flag lowers it to Member, but owner-only-billing takes precedence.
 */
export function getMinimumUsageSpendReadAccessLevel(
    memberUsageSpendReadAccess: boolean,
    ownerOnlyBilling: boolean
): OrganizationMembershipLevel {
    if (ownerOnlyBilling) {
        return OrganizationMembershipLevel.Owner
    }
    return memberUsageSpendReadAccess ? OrganizationMembershipLevel.Member : OrganizationMembershipLevel.Admin
}

/**
 * Determines if the user can view the read-only billing usage/spend tabs based on their org membership level.
 */
export function canViewUsageAndSpend(
    membershipLevel: number | null | undefined,
    memberUsageSpendReadAccess: boolean,
    ownerOnlyBilling: boolean
): boolean {
    if (!membershipLevel) {
        return false
    }
    return membershipLevel >= getMinimumUsageSpendReadAccessLevel(memberUsageSpendReadAccess, ownerOnlyBilling)
}
