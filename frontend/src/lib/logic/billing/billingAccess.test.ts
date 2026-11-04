import { FEATURE_FLAGS, OrganizationMembershipLevel } from 'lib/constants'
import type { FeatureFlagsSet } from 'lib/logic/featureFlagLogic'

import {
    canAccessBilling,
    canViewUsageAndSpend,
    getMinimumBillingAccessLevel,
    getMinimumUsageSpendReadAccessLevel,
    isMemberUsageSpendReadAccessEnabled,
} from './billingAccess'

describe('getMinimumBillingAccessLevel', () => {
    it('returns Admin when ownerOnlyBilling is false', () => {
        expect(getMinimumBillingAccessLevel(false)).toBe(OrganizationMembershipLevel.Admin)
    })

    it('returns Owner when ownerOnlyBilling is true', () => {
        expect(getMinimumBillingAccessLevel(true)).toBe(OrganizationMembershipLevel.Owner)
    })
})

describe('canAccessBilling', () => {
    it.each([
        { level: OrganizationMembershipLevel.Owner, ownerOnly: false, expected: true },
        { level: OrganizationMembershipLevel.Owner, ownerOnly: true, expected: true },
        { level: OrganizationMembershipLevel.Admin, ownerOnly: false, expected: true },
        { level: OrganizationMembershipLevel.Admin, ownerOnly: true, expected: false },
        { level: OrganizationMembershipLevel.Member, ownerOnly: false, expected: false },
        { level: OrganizationMembershipLevel.Member, ownerOnly: true, expected: false },
        { level: null, ownerOnly: false, expected: false },
        { level: null, ownerOnly: true, expected: false },
    ])('returns $expected for level=$level, ownerOnly=$ownerOnly', ({ level, ownerOnly, expected }) => {
        expect(canAccessBilling(level, ownerOnly)).toBe(expected)
    })
})

describe('getMinimumUsageSpendReadAccessLevel', () => {
    it.each([
        { memberAccess: false, ownerOnly: false, expected: OrganizationMembershipLevel.Admin },
        { memberAccess: true, ownerOnly: false, expected: OrganizationMembershipLevel.Member },
        { memberAccess: false, ownerOnly: true, expected: OrganizationMembershipLevel.Owner },
        // owner-only-billing wins over member-billing-usage-spend-read-access
        { memberAccess: true, ownerOnly: true, expected: OrganizationMembershipLevel.Owner },
    ])(
        'returns $expected for memberAccess=$memberAccess, ownerOnly=$ownerOnly',
        ({ memberAccess, ownerOnly, expected }) => {
            expect(getMinimumUsageSpendReadAccessLevel(memberAccess, ownerOnly)).toBe(expected)
        }
    )
})

describe('canViewUsageAndSpend', () => {
    it.each([
        { level: OrganizationMembershipLevel.Member, memberAccess: true, ownerOnly: false, expected: true },
        { level: OrganizationMembershipLevel.Member, memberAccess: true, ownerOnly: true, expected: false },
        { level: OrganizationMembershipLevel.Member, memberAccess: false, ownerOnly: false, expected: false },
        { level: OrganizationMembershipLevel.Admin, memberAccess: false, ownerOnly: false, expected: true },
        { level: OrganizationMembershipLevel.Admin, memberAccess: true, ownerOnly: true, expected: false },
        { level: OrganizationMembershipLevel.Owner, memberAccess: false, ownerOnly: true, expected: true },
        { level: null, memberAccess: true, ownerOnly: false, expected: false },
    ])(
        'returns $expected for level=$level, memberAccess=$memberAccess, ownerOnly=$ownerOnly',
        ({ level, memberAccess, ownerOnly, expected }) => {
            expect(canViewUsageAndSpend(level, memberAccess, ownerOnly)).toBe(expected)
        }
    )
})

describe('isMemberUsageSpendReadAccessEnabled', () => {
    it.each<{ case: string; featureFlags: FeatureFlagsSet; expected: boolean }>([
        {
            case: 'the grant is on',
            featureFlags: { [FEATURE_FLAGS.MEMBER_BILLING_USAGE_SPEND_READ_ACCESS]: true },
            expected: true,
        },
        {
            case: 'the grant is off',
            featureFlags: { [FEATURE_FLAGS.MEMBER_BILLING_USAGE_SPEND_READ_ACCESS]: false },
            expected: false,
        },
        { case: 'the flag is not present', featureFlags: {}, expected: false },
    ])('returns $expected when $case', ({ featureFlags, expected }) => {
        expect(isMemberUsageSpendReadAccessEnabled(featureFlags)).toBe(expected)
    })
})
