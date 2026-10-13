/* oxlint-disable react-hooks/rules-of-hooks -- useMocks is a test helper, not a React hook */
import { expectLogic } from 'kea-test-utils'

import { billingLogic } from 'scenes/billing/billingLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'

import { billingJson } from '~/mocks/fixtures/_billing'
import preflightJson from '~/mocks/fixtures/_preflight.json'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { AvailableFeature, BillingType } from '~/types'

import { payGateMiniLogic } from './payGateMiniLogic'

describe('payGateMiniLogic', () => {
    it.each([
        {
            name: 'disables the payment entry button',
            subscriptionLevel: 'free' as const,
            expected: {
                isPaymentEntryFlow: true,
                ctaDisabledReason: 'Billing for this organization is managed by Example Partner.',
            },
        },
        {
            name: 'keeps the link to the billing page enabled',
            subscriptionLevel: 'paid' as const,
            expected: { isPaymentEntryFlow: false, ctaDisabledReason: null },
        },
    ])('$name when a partner manages billing', async ({ subscriptionLevel, expected }) => {
        const billing: BillingType = {
            ...billingJson,
            customer_id: '',
            subscription_level: subscriptionLevel,
            billing_managed_by_partner: { partner_name: 'Example Partner' },
        }
        useMocks({
            get: {
                '/_preflight': [200, { ...preflightJson, cloud: true }],
                '/api/billing': [200, billing],
            },
        })
        initKeaTests()
        await expectLogic(preflightLogic).toFinishAllListeners()
        billingLogic.mount()
        await expectLogic(billingLogic, () => billingLogic.actions.loadBilling()).toFinishAllListeners()
        const logic = payGateMiniLogic({ feature: AvailableFeature.SUBSCRIPTIONS })
        logic.mount()

        expect(logic.values).toMatchObject({ gateVariant: 'add-card', ...expected })
    })
})
