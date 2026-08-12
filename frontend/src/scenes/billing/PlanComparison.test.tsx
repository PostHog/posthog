/* oxlint-disable react-hooks/rules-of-hooks -- useMocks is a test helper, not a React hook */
import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import { Provider } from 'kea'
import { expectLogic } from 'kea-test-utils'

import { billingUnsubscribedJson } from '~/mocks/fixtures/_billing_unsubscribed'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { BillingProductV2Type, BillingType } from '~/types'

import { billingLogic } from './billingLogic'
import { PlanComparison } from './PlanComparison'

const billing = billingUnsubscribedJson as unknown as BillingType

const getProduct = (type: string): BillingProductV2Type =>
    billing.products.find((product) => product.type === type) as BillingProductV2Type

describe('PlanComparison', () => {
    beforeEach(async () => {
        initKeaTests()
        useMocks({ get: { '/api/billing': () => [200, billing] } })
        billingLogic.mount()
        await expectLogic(billingLogic, () => billingLogic.actions.loadBilling()).toFinishAllListeners()
    })

    afterEach(() => {
        cleanup()
    })

    it('shows the events data retention window per plan when comparing platform plans', () => {
        render(
            <Provider>
                <PlanComparison product={getProduct('platform_and_support')} />
            </Provider>
        )

        const row = screen.getByRole('row', { name: /Events data retention/ })
        expect(row).toHaveTextContent('1 year')
        expect(row).toHaveTextContent('7 years')
    })

    it("doesn't duplicate the retention row on product analytics, which lists it as a feature", () => {
        render(
            <Provider>
                <PlanComparison product={getProduct('product_analytics')} />
            </Provider>
        )

        expect(screen.queryByRole('row', { name: /Events data retention/ })).not.toBeInTheDocument()
        expect(screen.getByRole('row', { name: /Data retention/ })).toHaveTextContent('7 years')
    })
})
