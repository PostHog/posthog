/* oxlint-disable react-hooks/rules-of-hooks -- useMocks is a test helper, not a React hook */
import '@testing-library/jest-dom'

import { act, cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Provider } from 'kea'
import { expectLogic } from 'kea-test-utils'

import { billingJson } from '~/mocks/fixtures/_billing'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { BillingProductV2Type, BillingType } from '~/types'

import { BillingLimit } from './BillingLimit'
import { billingLogic } from './billingLogic'

// Zero out current/projected usage so submitting never triggers the below-usage warning
// dialog — this test is about the Save/Remove button wiring, not that branch.
const makeProduct = (): BillingProductV2Type => ({
    ...(billingJson.products.find((p) => p.type === 'product_analytics') as BillingProductV2Type),
    subscribed: true,
    inclusion_only: false,
    current_amount_usd: null,
    projected_amount_usd: null,
})

describe('BillingLimit', () => {
    let patchedBody: any = null

    const seedBilling = async (customLimits: BillingType['custom_limits_usd']): Promise<void> => {
        const billingSeed = { ...billingJson, custom_limits_usd: customLimits }
        useMocks({
            get: { '/api/billing': () => [200, billingSeed] },
            patch: {
                '/api/billing': async ({ request }) => {
                    patchedBody = await request.json()
                    return [200, billingSeed]
                },
            },
        })
        billingLogic.mount()
        await expectLogic(billingLogic, () => billingLogic.actions.loadBilling()).toFinishAllListeners()
    }

    beforeEach(() => {
        initKeaTests()
        patchedBody = null
    })

    afterEach(async () => {
        cleanup()
        await act(async () => {
            await new Promise((r) => setTimeout(r, 0))
        })
        document.querySelectorAll('body > div:not(#root)').forEach((el) => el.remove())
    })

    it('saving a new limit PATCHes billing with the entered value under custom_limits_usd', async () => {
        await seedBilling({})
        render(
            <Provider>
                <BillingLimit product={makeProduct()} />
            </Provider>
        )

        await userEvent.click(await screen.findByText('Set a billing limit'))
        const input = screen.getByTestId('billing-limit-input-product_analytics')
        await userEvent.clear(input)
        await userEvent.type(input, '2000')
        await userEvent.click(screen.getByTestId('save-billing-limit-product_analytics'))

        await waitFor(() => expect(patchedBody).toEqual({ custom_limits_usd: { product_analytics: 2000 } }))
    })

    it('removing an existing limit PATCHes billing with a null limit', async () => {
        await seedBilling({ product_analytics: 500 })
        render(
            <Provider>
                <BillingLimit product={makeProduct()} />
            </Provider>
        )

        await userEvent.click(await screen.findByText('Edit limit'))
        await userEvent.click(screen.getByTestId('remove-billing-limit-product_analytics'))

        await waitFor(() => expect(patchedBody).toEqual({ custom_limits_usd: { product_analytics: null } }))
    })
})
