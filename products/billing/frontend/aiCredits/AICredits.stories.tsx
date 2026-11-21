import { Meta, StoryObj } from '@storybook/react'
import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { dayjs } from 'lib/dayjs'

import { mswDecorator } from '~/mocks/browser'
import { billingJson } from '~/mocks/fixtures/_billing'
import preflightJson from '~/mocks/fixtures/_preflight.json'

import { AICredits } from './AICredits'
import { aiCreditsLogic } from './aiCreditsLogic'

const RELOAD_ON = {
    low_balance_threshold_usd: '20.00',
    automatic_reload: {
        enabled: true,
        target_usd: '100.00',
        monthly_reload_limit_usd: '300.00',
        disabled_reason: null,
        disabled_at: null,
    },
}

const RELOAD_OFF_AFTER_DECLINE = {
    low_balance_threshold_usd: '20.00',
    automatic_reload: {
        enabled: false,
        target_usd: '100.00',
        monthly_reload_limit_usd: null,
        disabled_reason: 'card_declined',
        disabled_at: '2026-11-02T09:30:00Z',
    },
}

const HISTORY = {
    has_more: false,
    in_progress: [] as Record<string, unknown>[],
    results: [
        {
            created_at: '2026-11-02T10:14:00Z',
            kind: 'purchase',
            amount_usd: '50.00',
            tax_usd: '4.13',
            total_usd: '54.13',
            status: 'pending',
            receipt_url: 'https://pay.stripe.com/receipts/example-1',
        },
        {
            created_at: '2026-10-30T03:41:00Z',
            kind: 'automatic_reload',
            amount_usd: '100.00',
            tax_usd: '8.25',
            total_usd: '108.25',
            status: 'added',
            receipt_url: 'https://pay.stripe.com/receipts/example-2',
        },
        {
            created_at: '2026-10-24T18:02:00Z',
            kind: 'automatic_reload',
            amount_usd: '100.00',
            tax_usd: '8.25',
            total_usd: '108.25',
            status: 'added',
            receipt_url: 'https://pay.stripe.com/receipts/example-3',
        },
        {
            created_at: '2026-10-18T09:30:00Z',
            kind: 'purchase',
            amount_usd: '200.00',
            tax_usd: '16.50',
            total_usd: '216.50',
            status: 'added',
            receipt_url: 'https://pay.stripe.com/receipts/example-4',
        },
    ],
}

const PRODUCTS = [
    { product: 'self_driving', name: 'Self-driving', share: 0.72, free: 10 },
    {
        product: 'posthog_ai',
        name: 'PostHog AI',
        share: 0.14,
        free: 10,
    },
    {
        product: 'replay_vision',
        name: 'Replay vision',
        share: 0.08,
        free: 5,
    },
    { product: 'posthog_code', name: 'PostHog Code', share: 0.04, free: 0 },
    { product: 'ai_workflows', name: 'AI workflows', share: 0.02, free: 5 },
]

// The current period starts on Oct 18, and its days run up to the story's date, Nov 3. Earlier
// periods are full and a little quieter each month back.
const CURRENT_PERIOD_START = dayjs.utc('2026-10-18')
const DAY_TOTALS = [17.5, 14.8, 25.8, 13.4, 23.5, 19.6, 13.1, 22.7, 12.6, 21.4, 35.14, 14.2, 21.1, 29.6, 15.2, 16.9]

function spendFor(periodsAgo: number, balanceUsd: string): Record<string, unknown> {
    const start = CURRENT_PERIOD_START.subtract(periodsAgo, 'month')
    const end = CURRENT_PERIOD_START.subtract(periodsAgo - 1, 'month')
    const dayCount = periodsAgo === 0 ? DAY_TOTALS.length : end.diff(start, 'day')
    const scale = Math.max(1 - periodsAgo * 0.15, 0.2)
    const days = Array.from({ length: dayCount }, (_, index) => ({
        date: start.add(index, 'day').format('YYYY-MM-DD'),
        spend_usd: Object.fromEntries(
            PRODUCTS.map((p) => [p.product, (DAY_TOTALS[index % DAY_TOTALS.length] * scale * p.share).toFixed(6)])
        ),
    }))
    const productSpend = (product: string): number => days.reduce((sum, day) => sum + Number(day.spend_usd[product]), 0)
    return {
        balance_usd: balanceUsd,
        period_start: start.format('YYYY-MM-DD'),
        period_end: end.format('YYYY-MM-DD'),
        spend_usd: PRODUCTS.reduce((sum, p) => sum + productSpend(p.product), 0).toFixed(6),
        free_usd: PRODUCTS.reduce((sum, p) => sum + p.free, 0).toFixed(6),
        products: PRODUCTS.map((p) => ({
            product: p.product,
            name: p.name,
            spend_usd: productSpend(p.product).toFixed(6),
            free_usd: p.free.toFixed(6),
        })),
        days,
    }
}

const PROCESSING_PURCHASE = {
    created_at: '2026-11-03T09:12:00Z',
    amount_usd: '100.00',
    tax_usd: '8.25',
    total_usd: '108.25',
    status: 'processing',
    idempotency_key: 'example-purchase',
}

/** A null balance means the AI gateway doesn't answer. */
function mocks(
    settings: Record<string, unknown>,
    balanceUsd: string | null,
    limitUsd: string | null = '500.00',
    history: Record<string, unknown> = HISTORY
): ReturnType<typeof mswDecorator> {
    return mswDecorator({
        get: {
            '/_preflight': { ...preflightJson, cloud: true, realm: 'cloud' },
            '/api/billing/': { ...billingJson, stripe_portal_url: 'https://billing.stripe.com/p/session/example' },
            '/api/billing/ai_credits/settings/': settings,
            '/api/billing/ai_credits/card/': { card: { brand: 'visa', last4: '4242', exp_month: 8, exp_year: 2030 } },
            '/api/billing/ai_credits/history/': history,
            '/api/billing/ai_credits/quote/': { amount_usd: '50.00', tax_usd: '4.13', total_usd: '54.13' },
            // A balance of null stands for an AI gateway that doesn't answer, which also holds the limit.
            '/api/billing/ai_credits/spend_limit/': () =>
                balanceUsd === null
                    ? [
                          503,
                          {
                              code: 'ai_spend_limit_unavailable',
                              detail: "The AI spend limit isn't available right now.",
                          },
                      ]
                    : [200, { limit_usd: limitUsd }],
            '/api/billing/ai_credits/spend/': ({ request }) =>
                balanceUsd === null
                    ? [503, { code: 'ai_spend_unavailable', detail: "AI spend isn't available right now." }]
                    : [200, spendFor(Number(new URL(request.url).searchParams.get('periods_ago')), balanceUsd)],
        },
    })
}

const meta: Meta = {
    title: 'Scenes-Other/Billing/AI credits',
    component: AICredits,
    parameters: {
        layout: 'padded',
        viewMode: 'story',
        mockDate: '2026-11-03',
        // The page belongs to one scene, so its stories render in CI without keeping snapshots.
        testOptions: { snapshotBrowsers: [] },
    },
}
export default meta

type Story = StoryObj<typeof AICredits>

export const ReloadOn: Story = { decorators: [mocks(RELOAD_ON, '118.400000')] }

export const ReloadOffAfterADecline: Story = { decorators: [mocks(RELOAD_OFF_AFTER_DECLINE, '6.100000', null)] }

export const SpendNotReportedYet: Story = { decorators: [mocks(RELOAD_ON, null)] }

function AICreditsWithAddFundsOpen(): JSX.Element {
    const { openAddFundsModal } = useActions(aiCreditsLogic)
    useEffect(() => openAddFundsModal(), [openAddFundsModal])
    return <AICredits />
}

export const AddFunds: Story = {
    decorators: [mocks(RELOAD_OFF_AFTER_DECLINE, '6.100000', null)],
    render: () => <AICreditsWithAddFundsOpen />,
}

function AICreditsWithSettingsOpen(): JSX.Element {
    const { settings, spendLimit } = useValues(aiCreditsLogic)
    const { openSettingsModal } = useActions(aiCreditsLogic)
    // The modal fills its form from the settings and the spend limit, so it opens once both have loaded.
    useEffect(() => {
        if (settings && spendLimit) {
            openSettingsModal()
        }
    }, [settings, spendLimit, openSettingsModal])
    return <AICredits />
}

export const SpendSettings: Story = {
    decorators: [mocks(RELOAD_ON, '118.400000')],
    render: () => <AICreditsWithSettingsOpen />,
}

function AICreditsWithAnEarlierPeriod(): JSX.Element {
    const { periodOptions } = useValues(aiCreditsLogic)
    const { selectPeriod } = useActions(aiCreditsLogic)
    // The options come from the current period, so the story picks one once they exist.
    useEffect(() => {
        if (periodOptions.length > 0) {
            selectPeriod(1)
        }
    }, [periodOptions.length, selectPeriod])
    return <AICredits />
}

export const EarlierBillingPeriod: Story = {
    decorators: [mocks(RELOAD_ON, '118.400000')],
    render: () => <AICreditsWithAnEarlierPeriod />,
}

function AICreditsWithAPaymentStillConfirming(): JSX.Element {
    const { purchaseResumed, openAddFundsModal } = useActions(aiCreditsLogic)
    useEffect(() => {
        purchaseResumed(
            {
                key: PROCESSING_PURCHASE.idempotency_key,
                amountUsd: PROCESSING_PURCHASE.amount_usd,
                totalUsd: PROCESSING_PURCHASE.total_usd,
                startedAt: dayjs(PROCESSING_PURCHASE.created_at).valueOf(),
                organizationId: 'example-organization',
                reload: null,
            },
            'still_processing'
        )
        openAddFundsModal()
    }, [purchaseResumed, openAddFundsModal])
    return <AICredits />
}

export const PaymentStillConfirming: Story = {
    decorators: [mocks(RELOAD_ON, '118.400000', '500.00', { ...HISTORY, in_progress: [PROCESSING_PURCHASE] })],
    render: () => <AICreditsWithAPaymentStillConfirming />,
}
