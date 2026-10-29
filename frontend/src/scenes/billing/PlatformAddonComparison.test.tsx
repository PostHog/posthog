/* oxlint-disable react-hooks/rules-of-hooks -- useMocks is a test helper, not a React hook */
import '@testing-library/jest-dom'

import { cleanup, render } from '@testing-library/react'
import { Provider } from 'kea'
import { expectLogic } from 'kea-test-utils'

import { billingJson } from '~/mocks/fixtures/_billing'
import { makeBillingWithPlatformAddons } from '~/mocks/fixtures/_billing_platform_addons'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { BillingProductV2Type } from '~/types'

import { billingLogic } from './billingLogic'
import { PlatformAddonComparison } from './PlatformAddonComparison'

describe('PlatformAddonComparison', () => {
    const scrollIntoView = jest.fn()

    beforeEach(async () => {
        Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', { configurable: true, value: scrollIntoView })
        scrollIntoView.mockClear()
        useMocks({ get: { '/api/billing': () => [200, makeBillingWithPlatformAddons(billingJson, 'trial-used')] } })
        initKeaTests()
        billingLogic.mount()
        await expectLogic(billingLogic, () => billingLogic.actions.loadBilling()).toFinishAllListeners()
    })

    afterEach(() => {
        cleanup()
        delete (HTMLElement.prototype as Partial<HTMLElement>).scrollIntoView
    })

    it.each(['boost', 'scale', 'enterprise'])('scrolls to the %s plan card from the billing hero link', (type) => {
        const platform = billingLogic.values.billing?.products.find(
            (p) => p.type === 'platform_and_support'
        ) as BillingProductV2Type
        const { container } = render(
            <Provider>
                <PlatformAddonComparison product={platform} />
            </Provider>
        )
        const card = container.querySelector(`[data-attr="billing-product-addon-${type}"]`)
        expect(card).toBeInTheDocument()

        billingLogic.actions.scrollToProduct(type)

        expect(scrollIntoView).toHaveBeenCalledTimes(1)
        expect(scrollIntoView.mock.contexts[0]).toBe(card)
    })
})
