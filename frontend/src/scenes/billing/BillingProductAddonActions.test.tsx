/* oxlint-disable react-hooks/rules-of-hooks -- useMocks is a test helper, not a React hook */
import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import { Provider } from 'kea'
import { expectLogic } from 'kea-test-utils'

import { billingJson } from '~/mocks/fixtures/_billing'
import { makeBillingWithPlatformAddons } from '~/mocks/fixtures/_billing_platform_addons'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { BillingPlan, BillingProductV2AddonType, BillingType } from '~/types'

import { billingLogic } from './billingLogic'
import { BillingProductAddonActions } from './BillingProductAddonActions'

const onScale = makeBillingWithPlatformAddons(billingJson, 'on-scale')
const onBoostTrial: BillingType = {
    ...makeBillingWithPlatformAddons(billingJson, 'trial-available'),
    trial: { type: 'autosubscribe', status: 'active', target: 'boost', expires_at: '2024-04-01T00:00:00Z' },
}

const platformAddon = (billing: BillingType, type: BillingPlan): BillingProductV2AddonType | undefined =>
    billing.products
        .find((product) => product.type === 'platform_and_support')
        ?.addons.find((addon) => addon.type === type)

const ENTRY_POINTS = [
    {
        name: 'removing a subscribed package',
        billing: onScale,
        addonType: BillingPlan.Scale,
        find: () => screen.queryByTestId('more-button'),
    },
    {
        name: 'downgrading to a lower package',
        billing: onScale,
        addonType: BillingPlan.Boost,
        find: () => screen.queryByTestId('more-button'),
    },
    {
        name: 'cancelling a trial',
        billing: onBoostTrial,
        addonType: BillingPlan.Boost,
        find: () => screen.queryByText('Cancel trial'),
    },
]

describe('BillingProductAddonActions', () => {
    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
    })

    it.each(
        ENTRY_POINTS.flatMap((entryPoint) => [
            { ...entryPoint, payer: 'the organization', partner: null, offered: true },
            { ...entryPoint, payer: 'a partner', partner: { partner_name: 'Example Partner' }, offered: false },
        ])
    )('$name is offered: $offered, when $payer pays', async ({ billing, addonType, find, partner, offered }) => {
        useMocks({ get: { '/api/billing': [200, { ...billing, billing_managed_by_partner: partner }] } })
        billingLogic.mount()
        await expectLogic(billingLogic, () => billingLogic.actions.loadBilling()).toFinishAllListeners()
        const addon = platformAddon(billing, addonType)
        if (!addon) {
            throw new Error(`The fixture has no ${addonType} package`)
        }

        render(
            <Provider>
                <BillingProductAddonActions addon={addon} />
            </Provider>
        )

        expect(find() !== null).toBe(offered)
    })
})
