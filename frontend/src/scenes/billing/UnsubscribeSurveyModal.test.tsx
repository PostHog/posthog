import { MOCK_DEFAULT_ORGANIZATION } from 'lib/api.mock'

/* oxlint-disable react-hooks/rules-of-hooks -- useMocks is a test helper, not a React hook */
import '@testing-library/jest-dom'

import { act, cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Provider } from 'kea'
import { expectLogic } from 'kea-test-utils'

import { organizationLogic } from 'scenes/organizationLogic'

import { billingJson } from '~/mocks/fixtures/_billing'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { BillingProductV2AddonType, BillingProductV2Type, BillingType } from '~/types'

import { billingLogic } from './billingLogic'
import { UnsubscribeSurveyModal } from './UnsubscribeSurveyModal'

const productAnalytics = billingJson.products.find((p) => p.type === 'product_analytics') as BillingProductV2Type

describe('UnsubscribeSurveyModal', () => {
    let deactivatedProducts: string | null

    const seedBilling = async (overrides: Partial<BillingType> = {}): Promise<void> => {
        useMocks({
            get: { '/api/billing': () => [200, { ...billingJson, subscription_level: 'paid', ...overrides }] },
            post: {
                '/api/billing/deactivate': async ({ request }) => {
                    deactivatedProducts = ((await request.json()) as { products: string }).products
                    return [200, billingJson]
                },
            },
        })
        billingLogic.mount()
        organizationLogic.mount()
        await expectLogic(billingLogic, () => billingLogic.actions.loadBilling()).toFinishAllListeners()
    }

    const fillInSurvey = async (): Promise<void> => {
        await userEvent.click(await screen.findByText('Too expensive'))
        await userEvent.type(screen.getByTestId('unsubscribe-reason-survey-textarea'), 'It costs too much')
    }

    beforeEach(() => {
        initKeaTests()
        deactivatedProducts = null
    })

    afterEach(async () => {
        cleanup()
        await act(async () => {
            await new Promise((r) => setTimeout(r, 0))
        })
        document.querySelectorAll('body > div:not(#root)').forEach((el) => el.remove())
    })

    // A single confirm used to cancel every paid product, with no warning that a discount ends
    // or that ingestion stops, and nothing to distinguish it from removing one addon.
    it('warns about the discount and ingestion, and blocks the downgrade until the org name is typed', async () => {
        await seedBilling({ discount_percent: 30 })
        render(
            <Provider>
                <UnsubscribeSurveyModal product={productAnalytics} />
            </Provider>
        )

        expect(await screen.findByText(/cancels the whole subscription/)).toBeInTheDocument()
        expect(screen.getByText(/we stop ingesting your data/)).toBeInTheDocument()
        expect(screen.getByText(/Your 30% discount ends/)).toBeInTheDocument()

        await fillInSurvey()
        await userEvent.click(screen.getByRole('button', { name: 'Downgrade' }))
        expect(deactivatedProducts).toBeNull()

        await userEvent.type(
            screen.getByTestId('unsubscribe-confirmation-input'),
            MOCK_DEFAULT_ORGANIZATION.name.toUpperCase()
        )
        await userEvent.click(screen.getByRole('button', { name: 'Downgrade' }))

        expect(deactivatedProducts).toEqual('all_products')
    })

    it('removes a single addon without asking for a typed confirmation', async () => {
        await seedBilling()
        render(
            <Provider>
                <UnsubscribeSurveyModal product={productAnalytics.addons[0] as BillingProductV2AddonType} />
            </Provider>
        )

        await fillInSurvey()
        expect(screen.queryByTestId('unsubscribe-confirmation-input')).not.toBeInTheDocument()

        await userEvent.click(screen.getByRole('button', { name: 'Remove addon' }))

        expect(deactivatedProducts).toEqual(productAnalytics.addons[0].type)
    })
})
