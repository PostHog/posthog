import { MOCK_DEFAULT_ORGANIZATION } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { organizationLogic } from 'scenes/organizationLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { aiCreditsLogic } from './aiCreditsLogic'

const QUOTE = { amount_usd: '50.00', tax_usd: '4.13', total_usd: '54.13' }
const RELOAD_ON = {
    monthly_spend_limit_usd: null,
    low_balance_threshold_usd: '20.00',
    automatic_reload: {
        enabled: true,
        target_usd: '100.00',
        monthly_reload_limit_usd: null,
        disabled_reason: null,
        disabled_at: null,
    },
}

// The current period starts on Oct 18, so each read names its own period.
function spendFor(periodsAgo: number): Record<string, unknown> {
    const month = 10 - periodsAgo
    return {
        balance_usd: '100.000000',
        period_start: `2026-${String(month).padStart(2, '0')}-18`,
        period_end: `2026-${String(month + 1).padStart(2, '0')}-18`,
        spend_usd: '0.000000',
        free_usd: '0.000000',
        products: [],
        days: [],
    }
}

describe('aiCreditsLogic', () => {
    let logic: ReturnType<typeof aiCreditsLogic.build>
    let purchaseKeys: string[]
    let firstPurchaseAnswer: [number, Record<string, string>]

    beforeEach(() => {
        purchaseKeys = []
        useMocks({
            get: {
                '/api/billing/ai_credits/settings/': () => [
                    200,
                    {
                        monthly_spend_limit_usd: null,
                        low_balance_threshold_usd: null,
                        automatic_reload: {
                            enabled: false,
                            target_usd: null,
                            monthly_reload_limit_usd: null,
                            disabled_reason: null,
                            disabled_at: null,
                        },
                    },
                ],
                '/api/billing/ai_credits/card/': () => [
                    200,
                    { card: { brand: 'visa', last4: '4242', exp_month: 8, exp_year: 2030 } },
                ],
                '/api/billing/ai_credits/history/': () => [200, { results: [], has_more: false }],
                '/api/billing/ai_credits/quote/': ({ request }) => [
                    200,
                    { ...QUOTE, amount_usd: new URL(request.url).searchParams.get('amount_usd') },
                ],
                '/api/billing/ai_credits/spend/': ({ request }) => {
                    const periodsAgo = Number(new URL(request.url).searchParams.get('periods_ago'))
                    return [200, spendFor(periodsAgo)]
                },
            },
            post: {
                '/api/billing/ai_credits/purchase/': async ({ request }) => {
                    purchaseKeys.push(((await request.json()) as { idempotency_key: string }).idempotency_key)
                    return purchaseKeys.length === 1
                        ? firstPurchaseAnswer
                        : [200, { status: 'paid', total_usd: QUOTE.total_usd }]
                },
            },
        })
        initKeaTests()
        logic = aiCreditsLogic()
        logic.mount()
    })

    // Billing charges a key once. A retry after billing didn't answer has to reuse it, or billing can charge
    // the card twice. That holds also after the person reopens the modal and the quote reloads. A purchase
    // that ended without a charge, or a purchase of another amount, has to start over with a new key.
    it.each([
        ['billing never answered', 503, 'ai_credits_purchase_unfinished', 50, true],
        ['billing never answered and the amount changed', 503, 'ai_credits_purchase_unfinished', 100, false],
        ['the bank declined the card', 402, 'ai_credits_card_declined', 50, false],
        ['the purchase ended', 409, 'ai_credits_purchase_ended', 50, false],
    ])('pays again after %s with the right key', async (_, status, code, retryAmountUsd, sameKey) => {
        firstPurchaseAnswer = [status, { code, detail: 'PostHog says what happened' }]
        logic.actions.openAddFundsModal()
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.submitAddFundsForm()
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.purchaseError).toEqual('PostHog says what happened')

        logic.actions.closeAddFundsModal()
        logic.actions.openAddFundsModal()
        logic.actions.setAddFundsFormValue('amountUsd', retryAmountUsd)
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.submitAddFundsForm()
        await expectLogic(logic).toFinishAllListeners()

        expect(purchaseKeys).toHaveLength(2)
        expect(purchaseKeys[0] === purchaseKeys[1]).toEqual(sameKey)
        expect(logic.values.addFundsModalOpen).toEqual(false)

        // The second purchase completed, so the next one is a new purchase with a new key.
        logic.actions.openAddFundsModal()
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.submitAddFundsForm()
        await expectLogic(logic).toFinishAllListeners()

        expect(purchaseKeys).toHaveLength(3)
        expect(purchaseKeys[2]).not.toEqual(purchaseKeys[1])
    })

    it('pays for the organization the page loaded for after this tab loads another one', async () => {
        const purchaseOrganizations: string[] = []
        useMocks({
            post: {
                '/api/billing/ai_credits/purchase/': async ({ request }) => {
                    purchaseOrganizations.push(((await request.json()) as { organization_id: string }).organization_id)
                    return [200, { status: 'paid', total_usd: QUOTE.total_usd }]
                },
            },
        })
        organizationLogic.actions.loadCurrentOrganizationSuccess({ ...MOCK_DEFAULT_ORGANIZATION, id: 'another-org' })

        logic.actions.openAddFundsModal()
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.submitAddFundsForm()
        await expectLogic(logic).toFinishAllListeners()

        expect(purchaseOrganizations).toEqual([MOCK_DEFAULT_ORGANIZATION.id])
    })

    it('drops the failure of a quote that a newer quote replaced', async () => {
        let firstQuoteRequested!: () => void
        const firstQuoteStarted = new Promise<void>((resolve) => (firstQuoteRequested = resolve))
        let failFirstQuote!: () => void
        const firstQuoteFails = new Promise<void>((resolve) => (failFirstQuote = resolve))
        useMocks({
            get: {
                '/api/billing/ai_credits/quote/': async ({ request }) => {
                    const amountUsd = new URL(request.url).searchParams.get('amount_usd')
                    if (amountUsd !== '50.00') {
                        return [200, { ...QUOTE, amount_usd: amountUsd }]
                    }
                    firstQuoteRequested()
                    await firstQuoteFails
                    return [503, { code: 'ai_credits_tax_unavailable', detail: 'PostHog says what happened' }]
                },
            },
        })

        logic.actions.openAddFundsModal()
        await firstQuoteStarted
        logic.actions.setAddFundsFormValue('amountUsd', 100)
        failFirstQuote()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.quote?.amount_usd).toEqual('100.00')
        expect(logic.values.quoteError).toBeNull()
    })

    it('lets the person edit the settings only once they load', async () => {
        expect(logic.values.settingsEditDisabledReason).toEqual('Loading your settings')
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.settingsEditDisabledReason).toBeNull()

        logic.unmount()
        useMocks({ get: { '/api/billing/ai_credits/settings/': () => [500, { detail: 'Billing is down' }] } })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.settingsEditDisabledReason).toEqual("Your settings didn't load. Reload the page.")
    })

    // The card only matters when the person turns reload on. A failed card read must not turn it off.
    it.each([
        [
            'saves the amounts when the switch stays on',
            true,
            { low_balance_threshold_usd: '20.00', target_usd: '150.00', monthly_reload_limit_usd: null },
        ],
        ['turns reload off when the person switches it off', false, { enabled: false }],
    ])('with reload on and no card loaded, %s', async (_, reloadEnabled, expectedChange) => {
        const reloadSaves: Record<string, unknown>[] = []
        await expectLogic(logic).toFinishAllListeners()
        logic.unmount()
        useMocks({
            get: {
                '/api/billing/ai_credits/settings/': () => [200, RELOAD_ON],
                '/api/billing/ai_credits/card/': () => [500, { detail: 'Billing is down' }],
            },
            patch: {
                '/api/billing/ai_credits/settings/automatic_reload/': async ({ request }) => {
                    reloadSaves.push((await request.json()) as Record<string, unknown>)
                    return [200, RELOAD_ON]
                },
            },
        })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.openSettingsModal()
        logic.actions.setSpendSettingsFormValues({ reloadEnabled, targetUsd: 150 })
        logic.actions.submitSpendSettingsForm()
        await expectLogic(logic).toFinishAllListeners()

        expect(reloadSaves).toEqual([{ organization_id: MOCK_DEFAULT_ORGANIZATION.id, ...expectedChange }])
    })

    it('shows the chosen billing period, and keeps the balance and reloads on the current one', async () => {
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.selectPeriod(2)
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.spend?.period_start).toEqual('2026-08-18')
        expect(logic.values.spendSummary?.previousDailyAverageUsd).not.toBeNull()
        expect(logic.values.currentSpend?.period_start).toEqual('2026-10-18')

        logic.actions.selectPeriod(0)
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.spend?.period_start).toEqual('2026-10-18')
    })
})
