import { MOCK_DEFAULT_ORGANIZATION } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { organizationLogic } from 'scenes/organizationLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { aiCreditsLogic, polledPurchaseEntry } from './aiCreditsLogic'

const QUOTE = { amount_usd: '50.00', tax_usd: '4.13', total_usd: '54.13' }
const RELOAD_ON = {
    low_balance_threshold_usd: '20.00',
    automatic_reload: {
        enabled: true,
        target_usd: '100.00',
        monthly_reload_limit_usd: null,
        disabled_reason: null,
        disabled_at: null,
    },
}

function historyEntry(paymentId: string, status: 'pending' | 'added'): Record<string, unknown> {
    return {
        created_at: '2026-11-19T15:00:00Z',
        kind: 'purchase',
        amount_usd: '50.00',
        tax_usd: '4.13',
        total_usd: '54.13',
        status,
        payment_id: paymentId,
        receipt_url: null,
    }
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
    // Billing's answers after the first send, in order. Once they run out, billing answers paid.
    let laterPurchaseAnswers: [number, Record<string, string>][]

    beforeEach(() => {
        purchaseKeys = []
        laterPurchaseAnswers = []
        useMocks({
            get: {
                '/api/billing/ai_credits/settings/': () => [
                    200,
                    {
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
                '/api/billing/ai_credits/spend_limit/': () => [200, { limit_usd: '250.00' }],
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
                    if (purchaseKeys.length === 1) {
                        return firstPurchaseAnswer
                    }
                    return laterPurchaseAnswers.shift() ?? [200, { status: 'paid', total_usd: QUOTE.total_usd }]
                },
            },
        })
        initKeaTests()
        logic = aiCreditsLogic()
        logic.mount()
    })

    // Unmounting disposes the timer that reads the history again after a purchase.
    afterEach(() => {
        jest.useRealTimers()
        logic.unmount()
    })

    // Billing charges a key once. A retry after billing didn't answer has to reuse it, or billing can charge
    // the card twice. That holds also after the person reopens the modal and the quote reloads. A purchase
    // that ended without a charge, or a purchase of another amount, has to start over with a new key.
    it.each([
        ['billing never answered', 503, 'ai_credits_purchase_unfinished', 50, true],
        ['billing never answered and the amount changed', 503, 'ai_credits_purchase_unfinished', 100, false],
        ['the card issuer declined the card', 402, 'ai_credits_card_declined', 50, false],
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

    // The AI gateway holds the limit. When its read fails, the form can't know the limit, so a save must leave it.
    it('saves no spend limit when the limit did not load', async () => {
        const limitSaves: unknown[] = []
        await expectLogic(logic).toFinishAllListeners()
        logic.unmount()
        useMocks({
            get: { '/api/billing/ai_credits/spend_limit/': () => [503, { code: 'ai_spend_limit_unavailable' }] },
            patch: {
                '/api/billing/ai_credits/settings/spend_limit/': async ({ request }) => {
                    limitSaves.push(await request.json())
                    return [200, { limit_usd: '100.00' }]
                },
            },
        })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.openSettingsModal()
        logic.actions.setSpendSettingsFormValues({ noSpendLimit: false, spendLimitUsd: 100 })
        logic.actions.submitSpendSettingsForm()
        await expectLogic(logic).toFinishAllListeners()

        expect(limitSaves).toEqual([])
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

    describe('while billing still processes a purchase', () => {
        const PROCESSING: [number, Record<string, string>] = [202, { status: 'processing' }]

        beforeEach(async () => {
            firstPurchaseAnswer = PROCESSING
            logic.actions.openAddFundsModal()
            await expectLogic(logic).toFinishAllListeners()
        })

        it('sends the purchase again with the same key until billing answers paid', async () => {
            laterPurchaseAnswers = [PROCESSING]
            jest.useFakeTimers()

            logic.actions.submitAddFundsForm()
            await jest.advanceTimersByTimeAsync(0)
            expect(logic.values.purchaseStatus).toEqual('processing')
            expect(logic.values.addFundsModalOpen).toEqual(true)

            await jest.advanceTimersByTimeAsync(4000)
            await expectLogic(logic).toFinishAllListeners()

            expect(purchaseKeys).toHaveLength(3)
            expect(new Set(purchaseKeys).size).toEqual(1)
            expect(logic.values.purchaseStatus).toBeNull()
            expect(logic.values.unansweredPurchase).toBeNull()
            expect(logic.values.addFundsModalOpen).toEqual(false)
        })

        it('shows a decline that billing answers after processing', async () => {
            laterPurchaseAnswers = [[402, { code: 'ai_credits_card_declined', detail: 'Your card issuer declined' }]]
            jest.useFakeTimers()

            logic.actions.submitAddFundsForm()
            await jest.advanceTimersByTimeAsync(2000)
            await expectLogic(logic).toFinishAllListeners()

            expect(purchaseKeys).toHaveLength(2)
            expect(logic.values.purchaseStatus).toBeNull()
            expect(logic.values.purchaseError).toEqual('Your card issuer declined')
            expect(logic.values.unansweredPurchase).toBeNull()
            expect(logic.values.addFundsModalOpen).toEqual(true)
        })

        it('stops after the timeout and keeps the key, so paying again checks on the same purchase', async () => {
            laterPurchaseAnswers = Array.from({ length: 40 }, () => PROCESSING)
            jest.useFakeTimers()

            logic.actions.submitAddFundsForm()
            await jest.advanceTimersByTimeAsync(61_000)
            await expectLogic(logic).toFinishAllListeners()
            const sendsAtTimeout = purchaseKeys.length

            expect(logic.values.purchaseStatus).toEqual('still_processing')
            await jest.advanceTimersByTimeAsync(10_000)
            expect(purchaseKeys).toHaveLength(sendsAtTimeout)

            laterPurchaseAnswers = []
            logic.actions.submitAddFundsForm()
            await jest.advanceTimersByTimeAsync(0)
            await expectLogic(logic).toFinishAllListeners()

            expect(new Set(purchaseKeys).size).toEqual(1)
            expect(logic.values.addFundsModalOpen).toEqual(false)
        })

        it('turns automatic reload on only once the purchase is paid', async () => {
            const reloadSaves: Record<string, unknown>[] = []
            useMocks({
                patch: {
                    '/api/billing/ai_credits/settings/automatic_reload/': async ({ request }) => {
                        reloadSaves.push((await request.json()) as Record<string, unknown>)
                        return [200, RELOAD_ON]
                    },
                },
            })
            laterPurchaseAnswers = [PROCESSING]
            logic.actions.setAddFundsFormValue('reloadEnabled', true)
            jest.useFakeTimers()

            logic.actions.submitAddFundsForm()
            await jest.advanceTimersByTimeAsync(2000)
            expect(reloadSaves).toEqual([])

            await jest.advanceTimersByTimeAsync(2000)
            await expectLogic(logic).toFinishAllListeners()

            expect(reloadSaves).toHaveLength(1)
            expect(reloadSaves[0]).toMatchObject({ enabled: true })
        })
    })

    describe('after a purchase', () => {
        let historyReads: number
        let historyAnswers: Record<string, unknown>[][]

        beforeEach(async () => {
            historyReads = 0
            useMocks({
                get: {
                    '/api/billing/ai_credits/history/': () => {
                        const results = historyAnswers[Math.min(historyReads, historyAnswers.length - 1)]
                        historyReads += 1
                        return [200, { results, has_more: false }]
                    },
                },
            })
            firstPurchaseAnswer = [200, { status: 'paid', total_usd: QUOTE.total_usd, payment_id: 'pi_new' }]
            logic.actions.openAddFundsModal()
            await expectLogic(logic).toFinishAllListeners()
            historyReads = 0
        })

        it('reads the history again until the purchase is added, then reads the balance', async () => {
            historyAnswers = [[historyEntry('pi_new', 'pending')], [historyEntry('pi_new', 'added')]]
            jest.useFakeTimers()

            logic.actions.submitAddFundsForm()
            await jest.advanceTimersByTimeAsync(0)
            await expectLogic(logic).toFinishAllListeners()
            expect(historyReads).toEqual(1)
            expect(logic.values.polledPurchase?.paymentId).toEqual('pi_new')

            await expectLogic(logic, async () => {
                await jest.advanceTimersByTimeAsync(2000)
            }).toDispatchActions(['loadHistory', 'loadHistorySuccess', 'stopPollingHistory', 'loadCurrentSpend'])

            expect(historyReads).toEqual(2)
            expect(logic.values.polledPurchase).toBeNull()
            await jest.advanceTimersByTimeAsync(10_000)
            expect(historyReads).toEqual(2)
        })

        it('stops reading the history after the timeout and leaves the purchase pending', async () => {
            historyAnswers = [[historyEntry('pi_new', 'pending')]]
            jest.useFakeTimers()

            logic.actions.submitAddFundsForm()
            await jest.advanceTimersByTimeAsync(61_000)
            await expectLogic(logic).toFinishAllListeners()
            const readsAtTimeout = historyReads

            expect(readsAtTimeout).toBeGreaterThan(1)
            expect(logic.values.polledPurchase).toBeNull()
            expect(logic.values.history?.results[0]?.status).toEqual('pending')
            await jest.advanceTimersByTimeAsync(10_000)
            expect(historyReads).toEqual(readsAtTimeout)
        })
    })

    describe('polledPurchaseEntry', () => {
        const history = (...results: Record<string, unknown>[]): any => ({ results, has_more: false })

        it('finds a paid purchase by its payment', () => {
            const polled = { paymentId: 'pi_new', newestPaymentBefore: 'pi_old', startedAt: 0 }
            expect(
                polledPurchaseEntry(
                    history(historyEntry('pi_other', 'pending'), historyEntry('pi_new', 'added')),
                    polled
                )?.payment_id
            ).toEqual('pi_new')
        })

        it('takes a new newest entry for a purchase billing still processes', () => {
            const polled = { paymentId: null, newestPaymentBefore: 'pi_old', startedAt: 0 }
            expect(polledPurchaseEntry(history(historyEntry('pi_old', 'added')), polled)).toBeUndefined()
            expect(
                polledPurchaseEntry(history(historyEntry('pi_new', 'pending'), historyEntry('pi_old', 'added')), polled)
                    ?.payment_id
            ).toEqual('pi_new')
        })
    })
})
