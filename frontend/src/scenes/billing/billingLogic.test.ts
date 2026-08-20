import { MOCK_DEFAULT_ORGANIZATION } from 'lib/api.mock'

import { router } from 'kea-router'

import { FEATURE_FLAGS, OrganizationMembershipLevel } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { billingLogic } from 'scenes/billing/billingLogic'
import { organizationLogic } from 'scenes/organizationLogic'
import { urls } from 'scenes/urls'

import { ProductKey } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

type BillingAccessCase = {
    name: string
    membershipLevel: OrganizationMembershipLevel
    flags: Record<string, string | boolean>
    expected: {
        canAccessBilling: boolean
        canViewUsageAndSpend: boolean
        canOnlyViewUsageAndSpend: boolean
        billingEntryUrl: string | null
    }
}

describe('billingLogic', () => {
    beforeEach(() => {
        initKeaTests()
    })

    it.each(['/organization/billing', '/organization/billing/overview'])(
        'restores product deep-link scrolling from %s after mount',
        (pathname) => {
            billingLogic.mount()
            router.actions.push(pathname, { products: ProductKey.REPLAY_VISION })

            expect(billingLogic.values.scrollToProductKey).toBe(ProductKey.REPLAY_VISION)
        }
    )

    it.each(['/organization/billing', '/organization/billing/overview'])(
        'restores product deep-link scrolling from %s on initial mount',
        (pathname) => {
            router.actions.push(pathname, { products: ProductKey.REPLAY_VISION })
            billingLogic.mount()

            expect(billingLogic.values.scrollToProductKey).toBe(ProductKey.REPLAY_VISION)
        }
    )

    it.each(['/organization/billing/usage', '/organization/billing/spend'])(
        'does not restore product deep-link scrolling from %s after mount',
        (pathname) => {
            billingLogic.mount()
            router.actions.push(pathname, { products: ProductKey.REPLAY_VISION })

            expect(billingLogic.values.scrollToProductKey).toBe(null)
        }
    )

    it.each(['/organization/billing/usage', '/organization/billing/spend'])(
        'does not restore product deep-link scrolling from %s on initial mount',
        (pathname) => {
            router.actions.push(pathname, { products: ProductKey.REPLAY_VISION })
            billingLogic.mount()

            expect(billingLogic.values.scrollToProductKey).toBe(null)
        }
    )

    it.each<BillingAccessCase>([
        {
            name: 'member with both member-access flags',
            membershipLevel: OrganizationMembershipLevel.Member,
            flags: {
                [FEATURE_FLAGS.MEMBER_BILLING_USAGE_SPEND_READ_ACCESS]: true,
                [FEATURE_FLAGS.USAGE_SPEND_DASHBOARDS]: true,
            },
            expected: {
                canAccessBilling: false,
                canViewUsageAndSpend: true,
                canOnlyViewUsageAndSpend: true,
                billingEntryUrl: urls.organizationBillingSection('usage'),
            },
        },
        {
            name: 'member without the dashboards flag',
            membershipLevel: OrganizationMembershipLevel.Member,
            flags: {
                [FEATURE_FLAGS.MEMBER_BILLING_USAGE_SPEND_READ_ACCESS]: true,
                [FEATURE_FLAGS.USAGE_SPEND_DASHBOARDS]: false,
            },
            expected: {
                canAccessBilling: false,
                canViewUsageAndSpend: false,
                canOnlyViewUsageAndSpend: false,
                billingEntryUrl: null,
            },
        },
        {
            name: 'admin when owner-only billing is off',
            membershipLevel: OrganizationMembershipLevel.Admin,
            flags: {
                [FEATURE_FLAGS.OWNER_ONLY_BILLING]: false,
                [FEATURE_FLAGS.USAGE_SPEND_DASHBOARDS]: true,
            },
            expected: {
                canAccessBilling: true,
                canViewUsageAndSpend: true,
                canOnlyViewUsageAndSpend: false,
                billingEntryUrl: urls.organizationBillingSection('overview'),
            },
        },
        {
            name: 'admin when owner-only billing is on',
            membershipLevel: OrganizationMembershipLevel.Admin,
            flags: {
                [FEATURE_FLAGS.OWNER_ONLY_BILLING]: true,
                [FEATURE_FLAGS.USAGE_SPEND_DASHBOARDS]: true,
            },
            expected: {
                canAccessBilling: false,
                canViewUsageAndSpend: false,
                canOnlyViewUsageAndSpend: false,
                billingEntryUrl: null,
            },
        },
        {
            name: 'owner when owner-only billing is on',
            membershipLevel: OrganizationMembershipLevel.Owner,
            flags: {
                [FEATURE_FLAGS.OWNER_ONLY_BILLING]: true,
                [FEATURE_FLAGS.USAGE_SPEND_DASHBOARDS]: true,
            },
            expected: {
                canAccessBilling: true,
                canViewUsageAndSpend: true,
                canOnlyViewUsageAndSpend: false,
                billingEntryUrl: urls.organizationBillingSection('overview'),
            },
        },
    ])('sets billing access selectors for $name', ({ membershipLevel, flags, expected }) => {
        featureFlagLogic.mount()
        organizationLogic.mount()
        billingLogic.mount()

        organizationLogic.actions.loadCurrentOrganizationSuccess({
            ...MOCK_DEFAULT_ORGANIZATION,
            membership_level: membershipLevel,
        })
        featureFlagLogic.actions.setFeatureFlags(
            Object.entries(flags)
                .filter(([, value]) => value)
                .map(([key]) => key),
            flags
        )

        expect(billingLogic.values.canAccessBilling).toBe(expected.canAccessBilling)
        expect(billingLogic.values.canViewUsageAndSpend).toBe(expected.canViewUsageAndSpend)
        expect(billingLogic.values.canOnlyViewUsageAndSpend).toBe(expected.canOnlyViewUsageAndSpend)
        expect(billingLogic.values.billingEntryUrl).toBe(expected.billingEntryUrl)
    })
})
