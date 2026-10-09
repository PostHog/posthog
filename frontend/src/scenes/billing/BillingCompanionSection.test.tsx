/* oxlint-disable react-hooks/rules-of-hooks -- useMocks is a test helper, not a React hook */
import '@testing-library/jest-dom'

import { cleanup, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Provider } from 'kea'
import { expectLogic } from 'kea-test-utils'

import { billingJson } from '~/mocks/fixtures/_billing'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { BillingProductV2Type, BillingType } from '~/types'

import { Billing } from './Billing'
import { BillingCompanionSection } from './BillingCompanionSection'
import { billingLogic } from './billingLogic'
import { BillingProduct } from './BillingProduct'
import { PlanComparison } from './PlanComparison'

const replay = billingJson.products.find((p) => p.type === 'session_replay') as BillingProductV2Type
const productAnalytics = billingJson.products.find((p) => p.type === 'product_analytics') as BillingProductV2Type

const logs: BillingProductV2Type = {
    ...replay,
    type: 'logs',
    name: 'Logs',
    current_amount_usd: '100.00',
    projected_amount_usd: '200.00',
    projected_amount_usd_with_limit: '200.00',
}

const customRetention = ({ subscribed = true, onCurrentPlan = true } = {}): BillingProductV2Type => ({
    ...replay,
    type: 'logs_retention_custom',
    name: 'Logs custom retention',
    companion_of: 'logs',
    inclusion_only: true,
    no_billing_limit: true,
    addons: [],
    usage_limit: null,
    subscribed,
    plans: replay.plans.map((plan) => ({ ...plan, current_plan: onCurrentPlan })),
    current_amount_usd: '12.50',
    projected_amount_usd: '30.25',
})

const limitedCompanion: BillingProductV2Type = {
    ...customRetention(),
    type: 'logs_limited_extra',
    name: 'Logs limited extra',
    no_billing_limit: undefined,
    current_amount_usd: '40.00',
    projected_amount_usd: '80.00',
}

const seedBilling = async (products: BillingProductV2Type[], overrides: Partial<BillingType> = {}): Promise<void> => {
    useMocks({ get: { '/api/billing': () => [200, { ...billingJson, ...overrides, products }] } })
    billingLogic.mount()
    await expectLogic(billingLogic, () => billingLogic.actions.loadBilling()).toFinishAllListeners()
}

const renderSection = (product: BillingProductV2Type): void => {
    render(
        <Provider>
            <BillingCompanionSection product={product} />
        </Provider>
    )
}

describe('BillingCompanionSection', () => {
    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
    })

    it('shows a held companion with its amounts and a total that adds it to the parent', async () => {
        await seedBilling([logs, customRetention()])
        renderSection(logs)

        expect(screen.getByText('Not covered by your billing limit')).toBeInTheDocument()
        expect(screen.getByText('Your Logs billing limit does not cap these charges.')).toBeInTheDocument()
        const row = screen.getByTestId('billing-companion-logs_retention_custom')
        expect(row).toHaveTextContent('Custom retention')
        expect(row).toHaveTextContent('$12.50Month-to-date')
        expect(row).toHaveTextContent('$30.25Projected')
        expect(screen.getByTestId('billing-companions-total-logs')).toHaveTextContent(
            'Total including this section: $112.50 month-to-date, $230.25 projected'
        )

        await userEvent.click(screen.getByRole('button', { name: 'Show Custom retention details' }))
        expect(screen.getByRole('button', { name: 'Hide Custom retention details' })).toBeInTheDocument()
        expect(row.querySelector('.LemonTable')).toBeInTheDocument()
    })

    it('renders nothing when the parent holds no companion', async () => {
        await seedBilling([logs, customRetention({ subscribed: false, onCurrentPlan: false })])
        const { container } = render(
            <Provider>
                <BillingCompanionSection product={logs} />
            </Provider>
        )

        expect(container).toBeEmptyDOMElement()
    })

    it('renders nothing for a held companion that can have its own billing limit', async () => {
        await seedBilling([logs, limitedCompanion])
        const { container } = render(
            <Provider>
                <BillingCompanionSection product={logs} />
            </Provider>
        )

        expect(container).toBeEmptyDOMElement()
    })

    it('shows and totals only the companion that cannot have a billing limit', async () => {
        await seedBilling([logs, customRetention(), limitedCompanion])
        renderSection(logs)

        expect(screen.getByTestId('billing-companion-logs_retention_custom')).toBeInTheDocument()
        expect(screen.queryByTestId('billing-companion-logs_limited_extra')).not.toBeInTheDocument()
        expect(screen.getByTestId('billing-companions-total-logs')).toHaveTextContent(
            'Total including this section: $112.50 month-to-date, $230.25 projected'
        )
    })

    it('totals the parent at its projection capped by the billing limit', async () => {
        const cappedLogs = { ...logs, projected_amount_usd: '500.00', projected_amount_usd_with_limit: '200.00' }
        await seedBilling([cappedLogs, customRetention()])
        renderSection(cappedLogs)

        expect(screen.getByTestId('billing-companions-total-logs')).toHaveTextContent(
            'Total including this section: $112.50 month-to-date, $230.25 projected'
        )
    })

    it.each([
        {
            name: 'the parent is not subscribed and the companion is stale',
            parent: { ...logs, subscribed: false },
            companion: customRetention({ subscribed: false }),
            interval: 'month' as const,
            showsTotal: false,
        },
        {
            name: 'the plan bills yearly',
            parent: logs,
            companion: customRetention(),
            interval: 'year' as const,
            showsTotal: true,
        },
        {
            name: 'the parent has no billing limit',
            parent: { ...logs, no_billing_limit: true },
            companion: customRetention(),
            interval: 'month' as const,
            showsTotal: true,
        },
    ])(
        'keeps the rows but drops the limit sentence when $name',
        async ({ parent, companion, interval, showsTotal }) => {
            await seedBilling([parent, companion], {
                billing_period: { ...billingJson.billing_period!, interval },
            })
            renderSection(parent)

            expect(screen.getByText('Not covered by your billing limit')).toBeInTheDocument()
            expect(screen.getByTestId('billing-companion-logs_retention_custom')).toHaveTextContent(
                '$12.50Month-to-date'
            )
            expect(screen.queryByText(/billing limit does not cap these charges/)).not.toBeInTheDocument()
            expect(!!screen.queryByTestId('billing-companions-total-logs')).toBe(showsTotal)
        }
    )

    it('adds the companion rows to the header amounts of a parent without variants', async () => {
        const analytics = {
            ...productAnalytics,
            current_amount_usd: '40.10',
            projected_amount_usd_with_limit: '960.00',
        }
        const analyticsCompanion: BillingProductV2Type = {
            ...customRetention(),
            type: 'analytics_extra',
            name: 'Analytics extra',
            companion_of: 'product_analytics',
            current_amount_usd: '12.50',
            projected_amount_usd: '30.20',
        }
        await seedBilling([analytics, analyticsCompanion], { discount_percent: 10 })
        render(
            <Provider>
                <BillingProduct product={analytics} />
            </Provider>
        )

        // 10% off: header $36.09 + $864.00, companion $11.25 + $27.18.
        const card = screen.getByTestId('billing-product-product_analytics')
        expect(within(card).getByText('$36.09')).toBeInTheDocument()
        expect(within(card).getByText('$864.00')).toBeInTheDocument()
        const row = screen.getByTestId('billing-companion-analytics_extra')
        expect(row).toHaveTextContent('$11.25Month-to-date')
        expect(row).toHaveTextContent('$27.18Projected')
        expect(screen.getByTestId('billing-companions-total-product_analytics')).toHaveTextContent(
            'Total including this section: $47.34 month-to-date, $891.18 projected'
        )
    })

    it('sits on the parent card after the billing limit', async () => {
        await seedBilling([logs, customRetention()])
        render(
            <Provider>
                <BillingProduct product={logs} />
            </Provider>
        )

        const limit = screen.getByTestId('billing-limit-input-wrapper-logs')
        const section = screen.getByTestId('billing-companions-logs')
        expect(screen.getByTestId('billing-product-logs')).toContainElement(section)
        expect(limit.compareDocumentPosition(section) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    })
})

describe('a companion outside its parent card', () => {
    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
    })

    it('never gets its own product card, even when it is not inclusion-only', async () => {
        await seedBilling([logs, { ...customRetention(), inclusion_only: false }])
        render(
            <Provider>
                <Billing />
            </Provider>
        )

        expect(await screen.findByTestId('billing-product-logs')).toBeInTheDocument()
        expect(screen.queryByTestId('billing-product-logs_retention_custom')).not.toBeInTheDocument()
    })

    it('is left out of the included platform features in the plan comparison', async () => {
        const integrations = billingJson.products.find((p) => p.type === 'integrations') as BillingProductV2Type
        await seedBilling([productAnalytics, integrations, customRetention()], { has_active_subscription: false })
        render(
            <Provider>
                <PlanComparison product={productAnalytics} />
            </Provider>
        )

        expect(screen.getByText('Included platform features:')).toBeInTheDocument()
        expect(screen.getByText('Integrations')).toBeInTheDocument()
        expect(screen.queryByText('Logs custom retention')).not.toBeInTheDocument()
    })
})
