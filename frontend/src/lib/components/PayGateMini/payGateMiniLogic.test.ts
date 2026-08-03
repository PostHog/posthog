import { MOCK_DEFAULT_ORGANIZATION } from 'lib/api.mock'

/* oxlint-disable react-hooks/rules-of-hooks -- useMocks is a test helper, not a React hook */
import { expectLogic } from 'kea-test-utils'

import { OrganizationMembershipLevel } from 'lib/constants'
import { billingLogic } from 'scenes/billing/billingLogic'

import { billingUnsubscribedJson } from '~/mocks/fixtures/_billing_unsubscribed'
import preflightJson from '~/mocks/fixtures/_preflight.json'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { AvailableFeature } from '~/types'

import { payGateMiniLogic } from './payGateMiniLogic'

// group_analytics is an addon (not a core product), so isPaymentEntryFlow never kicks in here -
// the logic always falls through to the ctaLink/ctaLabel/ctaDisabledReason branch under test.
const FEATURE = AvailableFeature.GROUP_ANALYTICS

const seedBilling = async (membershipLevel: OrganizationMembershipLevel): Promise<void> => {
    // preflightLogic reads appContext.preflight synchronously on mount (no network round trip),
    // so setting it here - before initKeaTests - is enough to force the cloud "add-card" gate
    // instead of the self-hosted "move-to-cloud" one.
    window.POSTHOG_APP_CONTEXT = { preflight: { ...preflightJson, cloud: true, is_debug: true } } as any
    initKeaTests(true, undefined, undefined, { ...MOCK_DEFAULT_ORGANIZATION, membership_level: membershipLevel })

    useMocks({ get: { '/api/billing': () => [200, billingUnsubscribedJson] } })
    billingLogic.mount()
    await expectLogic(billingLogic, () => billingLogic.actions.loadBilling()).toFinishAllListeners()
}

describe('payGateMiniLogic', () => {
    let logic: ReturnType<typeof payGateMiniLogic.build>

    afterEach(() => {
        logic?.unmount()
    })

    // Regression guard: a non-admin used to get "View plans" linking to /organization/billing,
    // a page Billing.tsx blocks for members - a dead-end CTA. Below the org's billing access
    // level, the CTA must point non-admins at an admin instead of a page they can't read.
    it('sends admins to the billing page but tells members to ask an admin', async () => {
        await seedBilling(OrganizationMembershipLevel.Admin)
        logic = payGateMiniLogic({ feature: FEATURE })
        logic.mount()

        expect(logic.values.gateVariant).toBe('add-card')
        expect(logic.values.canAccessBilling).toBe(true)
        expect(logic.values.ctaLabel).toBe('View plans')
        expect(logic.values.ctaLink).toBe('/organization/billing?products=group_analytics')
        expect(logic.values.ctaDisabledReason).toBeUndefined()
        logic.unmount()

        await seedBilling(OrganizationMembershipLevel.Member)
        logic = payGateMiniLogic({ feature: FEATURE })
        logic.mount()

        expect(logic.values.gateVariant).toBe('add-card')
        expect(logic.values.canAccessBilling).toBe(false)
        expect(logic.values.ctaLabel).toBe('Ask an admin to upgrade')
        expect(logic.values.ctaLink).toBeUndefined()
        expect(logic.values.ctaDisabledReason).toBe('Ask an organization admin to upgrade your plan.')
    })
})
