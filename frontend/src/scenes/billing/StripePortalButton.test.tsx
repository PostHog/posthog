/* oxlint-disable react-hooks/rules-of-hooks -- useMocks is a test helper, not a React hook */
import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import { Provider } from 'kea'
import { expectLogic } from 'kea-test-utils'

import { billingJson } from '~/mocks/fixtures/_billing'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { BillingProvider, BillingType } from '~/types'

import { billingLogic } from './billingLogic'
import { StripePortalButton } from './StripePortalButton'

const EXTERNAL_INVOICES_URL = 'https://vercel.com/example-team/~/integrations/posthog/icfg_example/invoices'

describe('StripePortalButton', () => {
    const renderForBilling = async (billing: Partial<BillingType>): Promise<HTMLElement> => {
        useMocks({ get: { '/api/billing': [200, { ...billingJson, ...billing }] } })
        billingLogic.mount()
        await expectLogic(billingLogic, () => {
            billingLogic.actions.loadBilling()
        }).toFinishAllListeners()

        return render(
            <Provider>
                <StripePortalButton />
            </Provider>
        ).container
    }

    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
    })

    it.each([
        {
            name: 'the Stripe portal when PostHog bills the organization',
            billing: { billing_provider: BillingProvider.PostHog },
            expectedHref: billingJson.stripe_portal_url,
        },
        {
            name: 'the external provider invoices page',
            billing: { external_billing_provider_invoices_url: EXTERNAL_INVOICES_URL },
            expectedHref: EXTERNAL_INVOICES_URL,
        },
        {
            name: 'the external provider invoices page when billing has no customer id',
            billing: { external_billing_provider_invoices_url: EXTERNAL_INVOICES_URL, customer_id: '' },
            expectedHref: EXTERNAL_INVOICES_URL,
        },
    ])('links to $name', async ({ billing, expectedHref }) => {
        await renderForBilling(billing)

        expect(screen.getByText('Manage card details and invoices').closest('a')).toHaveAttribute('href', expectedHref)
    })

    it('renders nothing when an external provider has no invoices page', async () => {
        const container = await renderForBilling({ billing_provider: BillingProvider.Vercel })

        expect(container).toBeEmptyDOMElement()
    })
})
