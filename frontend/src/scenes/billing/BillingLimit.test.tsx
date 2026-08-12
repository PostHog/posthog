/* oxlint-disable react-hooks/rules-of-hooks -- useMocks is a test helper, not a React hook */
import '@testing-library/jest-dom'

import { act, cleanup, render, screen } from '@testing-library/react'
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
    name: 'PostHog Desktop (usage-based)',
    subscribed: true,
    inclusion_only: false,
    current_amount_usd: null,
    projected_amount_usd: null,
})

describe('BillingLimit', () => {
    let patchedBody: any = null
    let billingState: BillingType

    const seedBilling = async (customLimits: BillingType['custom_limits_usd']): Promise<void> => {
        billingState = { ...billingJson, custom_limits_usd: customLimits }
        useMocks({
            get: { '/api/billing': () => [200, billingState] },
            patch: {
                '/api/billing': async ({ request }) => {
                    patchedBody = await request.json()
                    // Persist the change like the backend does so the reload after save renders the new limit.
                    billingState = {
                        ...billingState,
                        custom_limits_usd: { ...billingState.custom_limits_usd, ...patchedBody.custom_limits_usd },
                    }
                    return [200, billingState]
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
        // Unmount so billingLogic's async listeners don't resolve after the test and log store errors.
        billingLogic.unmount()
        await act(async () => {
            await new Promise((r) => setTimeout(r, 0))
        })
        document.querySelectorAll('body > div:not(#root)').forEach((el) => el.remove())
    })

    // $0 is a real limit (drop all usage), not "no limit" — it must survive the save/reload
    // round-trip and render, which the billingProductLogic selector test alone can't prove.
    it.each([
        { entered: '2000', savedLimit: 2000, renderedAmount: '$2,000' },
        { entered: '0', savedLimit: 0, renderedAmount: '$0' },
    ])(
        'saving a limit ($entered) PATCHes it under custom_limits_usd and renders the saved value',
        async ({ entered, savedLimit, renderedAmount }) => {
            await seedBilling({})
            render(
                <Provider>
                    <BillingLimit product={makeProduct()} />
                </Provider>
            )

            await userEvent.click(await screen.findByText('Set a billing limit'))
            const input = screen.getByTestId('billing-limit-input-product_analytics')
            await userEvent.clear(input)
            await userEvent.type(input, entered)
            await userEvent.click(screen.getByTestId('save-billing-limit-product_analytics'))

            expect(await screen.findByTestId('billing-limit-set-product_analytics')).toHaveTextContent(
                `You have a ${renderedAmount} billing limit set for PostHog Desktop (usage-based).`
            )
            expect(patchedBody).toEqual({ custom_limits_usd: { product_analytics: savedLimit } })
        }
    )

    // When you lower a limit below your usage, the backend pins the current period to your usage and
    // defers the lower number to next period, so the two limits differ. The page must label the
    // in-force current-period limit as such, not leave it reading like the next-period number is live.
    const seedTwoLimits = async (current: number, next: number): Promise<void> => {
        billingState = {
            ...billingJson,
            custom_limits_usd: { product_analytics: current },
            next_period_custom_limits_usd: { product_analytics: next },
        }
        useMocks({ get: { '/api/billing': () => [200, billingState] } })
        billingLogic.mount()
        await expectLogic(billingLogic, () => billingLogic.actions.loadBilling()).toFinishAllListeners()
    }

    it('labels the pinned current-period limit and still shows the deferred next-period limit', async () => {
        await seedTwoLimits(150, 100)
        render(
            <Provider>
                <BillingLimit product={makeProduct()} />
            </Provider>
        )

        expect(await screen.findByTestId('billing-limit-current-period-product_analytics')).toHaveTextContent(
            'Your limit for the current period is $150. We set it to your usage when you lowered the limit below it.'
        )
        expect(screen.getByText(/Your limit for next period/)).toHaveTextContent('$100')
    })

    it('points at the current-period limit to raise when usage is over it', async () => {
        await seedTwoLimits(150, 100)
        render(
            <Provider>
                <BillingLimit product={{ ...makeProduct(), percentage_usage: 1.2 }} />
            </Provider>
        )

        expect(await screen.findByTestId('billing-limit-over-current-period-product_analytics')).toHaveTextContent(
            'Your usage is over your current-period limit of $150, so we are dropping data. Raise this limit to start ingestion again. Your $100 limit applies from next period.'
        )
    })

    it('removing an existing limit PATCHes a null limit and re-renders as unset', async () => {
        await seedBilling({ product_analytics: 500 })
        render(
            <Provider>
                <BillingLimit product={makeProduct()} />
            </Provider>
        )

        await userEvent.click(await screen.findByText('Edit limit'))
        await userEvent.click(screen.getByTestId('remove-billing-limit-product_analytics'))

        expect(await screen.findByTestId('billing-limit-not-set-product_analytics')).toHaveTextContent(
            'You do not have a billing limit set for PostHog Desktop (usage-based).'
        )
        expect(patchedBody).toEqual({ custom_limits_usd: { product_analytics: null } })
    })
})
