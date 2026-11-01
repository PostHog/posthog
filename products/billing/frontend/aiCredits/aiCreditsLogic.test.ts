import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { aiCreditsLogic } from './aiCreditsLogic'

const QUOTE = { amount_usd: '50.00', tax_usd: '4.13', total_usd: '54.13' }

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
                '/api/billing/ai_credits/quote/': () => [200, QUOTE],
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

    // Billing charges a key once. A retry after billing didn't answer has to reuse it, or the card
    // can be charged twice. A purchase that ended without a charge has to start over with a new key.
    it.each([
        ['billing never answered', 503, 'ai_credits_purchase_unfinished', true],
        ['the bank declined the card', 402, 'ai_credits_card_declined', false],
        ['the purchase ended', 409, 'ai_credits_purchase_ended', false],
    ])('pays again after %s with the right key', async (_, status, code, sameKey) => {
        firstPurchaseAnswer = [status, { code, detail: 'PostHog says what happened' }]
        logic.actions.openAddFundsModal()
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.submitAddFundsForm()
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.purchaseError).toEqual('PostHog says what happened')

        logic.actions.submitAddFundsForm()
        await expectLogic(logic).toFinishAllListeners()

        expect(purchaseKeys).toHaveLength(2)
        expect(purchaseKeys[0] === purchaseKeys[1]).toEqual(sameKey)
        expect(logic.values.addFundsModalOpen).toEqual(false)
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
