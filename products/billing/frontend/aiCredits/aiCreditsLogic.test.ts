import { MOCK_DEFAULT_ORGANIZATION } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { lemonToast } from '@posthog/lemon-ui'

import { organizationLogic } from 'scenes/organizationLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { aiCreditsLogic } from './aiCreditsLogic'

const mockHandleNextAction = jest.fn()
jest.mock('@stripe/stripe-js', () => ({
    loadStripe: () => Promise.resolve({ handleNextAction: mockHandleNextAction }),
}))

type BillingAnswer = [number, Record<string, string>]

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
const STORED_PURCHASE_KEY = `ai-credits-unanswered-purchase-${MOCK_DEFAULT_ORGANIZATION.id}`

const PROCESSING: BillingAnswer = [202, { status: 'processing' }]
const PAID: BillingAnswer = [200, { status: 'paid', total_usd: QUOTE.total_usd, payment_id: 'pi_new' }]
const CREDIT_PENDING: BillingAnswer = [200, { ...PAID[1], credit_status: 'pending' }]
const CREDIT_ADDED: BillingAnswer = [200, { ...PAID[1], credit_status: 'added' }]
const DECLINED: BillingAnswer = [402, { code: 'ai_credits_card_declined', detail: 'Your card issuer declined' }]
const REQUIRES_ACTION: BillingAnswer = [
    200,
    { status: 'requires_action', total_usd: QUOTE.total_usd, payment_id: 'pi_new', client_secret: 'pi_new_secret' },
]

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

function storePurchase(startedAt: number): string {
    const key = 'stored-purchase'
    localStorage.setItem(
        STORED_PURCHASE_KEY,
        JSON.stringify({
            key,
            amountUsd: QUOTE.amount_usd,
            totalUsd: QUOTE.total_usd,
            startedAt,
            organizationId: MOCK_DEFAULT_ORGANIZATION.id,
            reload: null,
        })
    )
    return key
}

describe('aiCreditsLogic', () => {
    let logic: ReturnType<typeof aiCreditsLogic.build>
    let purchaseKeys: string[]
    let firstPurchaseAnswer: BillingAnswer
    // Billing's answers after the first send, in order. Once they run out, billing answers paid.
    let laterPurchaseAnswers: BillingAnswer[]
    // The key of each status read, and billing's answers to them in order. Once they run out, billing answers that
    // it added the credit.
    let statusReads: string[]
    let statusAnswers: BillingAnswer[]
    let historyReads: number

    beforeEach(() => {
        localStorage.clear()
        purchaseKeys = []
        laterPurchaseAnswers = []
        statusReads = []
        statusAnswers = []
        historyReads = 0
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
                '/api/billing/ai_credits/history/': () => {
                    historyReads += 1
                    return [200, { in_progress: [], results: [], has_more: false }]
                },
                '/api/billing/ai_credits/spend_limit/': () => [200, { limit_usd: '250.00' }],
                '/api/billing/ai_credits/quote/': ({ request }) => [
                    200,
                    { ...QUOTE, amount_usd: new URL(request.url).searchParams.get('amount_usd') },
                ],
                '/api/billing/ai_credits/spend/': ({ request }) => {
                    const periodsAgo = Number(new URL(request.url).searchParams.get('periods_ago'))
                    return [200, spendFor(periodsAgo)]
                },
                '/api/billing/ai_credits/purchase/:key/': ({ params }) => {
                    statusReads.push(String(params.key))
                    return statusAnswers.shift() ?? CREDIT_ADDED
                },
            },
            post: {
                '/api/billing/ai_credits/purchase/': async ({ request }) => {
                    purchaseKeys.push(((await request.json()) as { idempotency_key: string }).idempotency_key)
                    if (purchaseKeys.length === 1) {
                        return firstPurchaseAnswer
                    }
                    return laterPurchaseAnswers.shift() ?? PAID
                },
            },
        })
        initKeaTests()
        logic = aiCreditsLogic()
        logic.mount()
    })

    // Unmounting disposes the timers that read the status again.
    afterEach(() => {
        jest.useRealTimers()
        jest.restoreAllMocks()
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

    it('pays and reads the status for the organization the page loaded for after this tab loads another one', async () => {
        const purchaseOrganizations: string[] = []
        const statusOrganizations: (string | null)[] = []
        useMocks({
            get: {
                '/api/billing/ai_credits/purchase/:key/': ({ request }) => {
                    statusOrganizations.push(new URL(request.url).searchParams.get('organization_id'))
                    return CREDIT_ADDED
                },
            },
            post: {
                '/api/billing/ai_credits/purchase/': async ({ request }) => {
                    purchaseOrganizations.push(((await request.json()) as { organization_id: string }).organization_id)
                    return PROCESSING
                },
            },
        })
        organizationLogic.actions.loadCurrentOrganizationSuccess({ ...MOCK_DEFAULT_ORGANIZATION, id: 'another-org' })
        logic.actions.openAddFundsModal()
        await expectLogic(logic).toFinishAllListeners()
        jest.useFakeTimers()

        logic.actions.submitAddFundsForm()
        await jest.advanceTimersByTimeAsync(2000)
        await expectLogic(logic).toFinishAllListeners()

        expect(purchaseOrganizations).toEqual([MOCK_DEFAULT_ORGANIZATION.id])
        expect(statusOrganizations).toEqual([MOCK_DEFAULT_ORGANIZATION.id])
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
        beforeEach(async () => {
            firstPurchaseAnswer = PROCESSING
            logic.actions.openAddFundsModal()
            await expectLogic(logic).toFinishAllListeners()
        })

        it('reads the status every 2 s for 10 s, then every 5 to 10 s, and never sends the purchase again', async () => {
            // The slow reads wait 5 s plus half the 5 s spread.
            jest.spyOn(Math, 'random').mockReturnValue(0.5)
            statusAnswers = Array.from({ length: 10 }, () => PROCESSING)
            jest.useFakeTimers()

            logic.actions.submitAddFundsForm()
            await jest.advanceTimersByTimeAsync(0)
            expect(logic.values.purchaseStatus).toEqual('processing')
            expect(logic.values.payDisabledReason).toEqual('The payment is in progress')
            expect(localStorage.getItem(STORED_PURCHASE_KEY)).toContain(purchaseKeys[0])

            await jest.advanceTimersByTimeAsync(10_000)
            expect(statusReads).toHaveLength(5)
            await jest.advanceTimersByTimeAsync(7499)
            expect(statusReads).toHaveLength(5)
            await jest.advanceTimersByTimeAsync(1)
            expect(statusReads).toHaveLength(6)

            expect(purchaseKeys).toHaveLength(1)
            expect(new Set(statusReads)).toEqual(new Set(purchaseKeys))
        })

        it('stops reading at the cap, shows the payment as pending and keeps the purchase from starting again', async () => {
            statusAnswers = Array.from({ length: 40 }, () => PROCESSING)
            jest.useFakeTimers()

            logic.actions.submitAddFundsForm()
            await jest.advanceTimersByTimeAsync(121_000)
            await expectLogic(logic).toFinishAllListeners()
            const readsAtCap = statusReads.length

            expect(logic.values.purchaseStatus).toEqual('still_processing')
            expect(logic.values.payDisabledReason).toEqual("We're still confirming your last payment")
            await jest.advanceTimersByTimeAsync(60_000)
            expect(statusReads).toHaveLength(readsAtCap)

            // The form submits on Enter too, so the submit itself refuses while the purchase is pending.
            logic.actions.submitAddFundsForm()
            await jest.advanceTimersByTimeAsync(0)
            expect(purchaseKeys).toHaveLength(1)
        })

        it.each([
            ['a decline as an error', DECLINED, 'error', 'Your card issuer declined'],
            [
                'a payment as a success',
                CREDIT_PENDING,
                'success',
                'Payment received. Your AI credits show as pending until we add them to your balance.',
            ],
        ])('shows %s toast when the modal is closed', async (_, answer, toastKind, message) => {
            const toast = jest.spyOn(lemonToast, toastKind as 'error' | 'success').mockImplementation(() => 'toast')
            statusAnswers = [answer]
            jest.useFakeTimers()

            logic.actions.submitAddFundsForm()
            await jest.advanceTimersByTimeAsync(0)
            logic.actions.closeAddFundsModal()
            await jest.advanceTimersByTimeAsync(2000)
            await expectLogic(logic).toFinishAllListeners()

            expect(toast).toHaveBeenCalledWith(message)
            expect(logic.values.purchasePending).toEqual(false)
            expect(localStorage.getItem(STORED_PURCHASE_KEY)).toBeNull()
        })

        it('shows a decline in the modal while it is open, and pays again with a new key', async () => {
            statusAnswers = [DECLINED]
            jest.useFakeTimers()

            logic.actions.submitAddFundsForm()
            await jest.advanceTimersByTimeAsync(2000)
            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.purchaseError).toEqual('Your card issuer declined')
            expect(logic.values.unansweredPurchase).toBeNull()
            expect(logic.values.addFundsModalOpen).toEqual(true)
        })

        it('runs the card authentication that a status read asks for, and runs it once', async () => {
            window.STRIPE_PUBLIC_KEY = 'pk_test_example'
            mockHandleNextAction.mockResolvedValue({ paymentIntent: { status: 'succeeded' } })
            // Billing answers requires_action again until Stripe tells it about the payment.
            statusAnswers = [REQUIRES_ACTION, REQUIRES_ACTION, CREDIT_ADDED]
            jest.useFakeTimers()

            logic.actions.submitAddFundsForm()
            await jest.advanceTimersByTimeAsync(2000)
            await expectLogic(logic).toFinishAllListeners()

            expect(mockHandleNextAction).toHaveBeenCalledWith({ clientSecret: 'pi_new_secret' })
            expect(logic.values.purchasePending).toEqual(false)

            await jest.advanceTimersByTimeAsync(4000)
            await expectLogic(logic).toFinishAllListeners()

            expect(mockHandleNextAction).toHaveBeenCalledTimes(1)
            expect(statusReads).toHaveLength(3)
            expect(logic.values.followedCredit).toBeNull()
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
            statusAnswers = [PROCESSING, CREDIT_PENDING]
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

    describe('with a purchase that another page load left processing', () => {
        it.each([
            [
                'on mount',
                () => {
                    logic.unmount()
                    logic.mount()
                },
            ],
            ['on focus', () => window.dispatchEvent(new Event('focus'))],
        ])('reads it %s and follows it to its answer', async (_, resume) => {
            await expectLogic(logic).toFinishAllListeners()
            jest.useFakeTimers()
            const key = storePurchase(Date.now() - 30_000)
            statusAnswers = [PROCESSING, CREDIT_ADDED]

            resume()
            await jest.advanceTimersByTimeAsync(0)
            expect(statusReads).toEqual([key])
            expect(logic.values.purchaseStatus).toEqual('processing')
            expect(logic.values.payDisabledReason).toEqual('The payment is in progress')

            await jest.advanceTimersByTimeAsync(2000)
            await expectLogic(logic).toFinishAllListeners()

            expect(statusReads).toEqual([key, key])
            expect(logic.values.purchasePending).toEqual(false)
            expect(localStorage.getItem(STORED_PURCHASE_KEY)).toBeNull()
        })

        it('reads it once on each focus after the cap', async () => {
            await expectLogic(logic).toFinishAllListeners()
            logic.unmount()
            jest.useFakeTimers()
            storePurchase(Date.now() - 5 * 60_000)
            statusAnswers = [PROCESSING, PROCESSING]

            logic.mount()
            await jest.advanceTimersByTimeAsync(30_000)
            expect(statusReads).toHaveLength(1)
            expect(logic.values.purchaseStatus).toEqual('still_processing')

            window.dispatchEvent(new Event('focus'))
            await jest.advanceTimersByTimeAsync(30_000)
            expect(statusReads).toHaveLength(2)
            expect(logic.values.purchaseStatus).toEqual('still_processing')
        })
    })

    describe('after billing answers paid', () => {
        beforeEach(async () => {
            firstPurchaseAnswer = PAID
            logic.actions.openAddFundsModal()
            await expectLogic(logic).toFinishAllListeners()
        })

        it('reads the credit status until billing adds the credit, then reloads the history', async () => {
            statusAnswers = [CREDIT_PENDING, CREDIT_ADDED]
            jest.useFakeTimers()

            logic.actions.submitAddFundsForm()
            await jest.advanceTimersByTimeAsync(0)
            await expectLogic(logic).toFinishAllListeners()
            const historyReadsAtPayment = historyReads

            await jest.advanceTimersByTimeAsync(4000)
            await expectLogic(logic).toFinishAllListeners()

            expect(statusReads).toEqual([purchaseKeys[0], purchaseKeys[0]])
            expect(historyReads).toEqual(historyReadsAtPayment + 1)
            await jest.advanceTimersByTimeAsync(10_000)
            expect(statusReads).toHaveLength(2)
        })

        it('stops reading the credit status at the cap and leaves the credit pending', async () => {
            statusAnswers = Array.from({ length: 40 }, () => CREDIT_PENDING)
            jest.useFakeTimers()

            logic.actions.submitAddFundsForm()
            await jest.advanceTimersByTimeAsync(121_000)
            await expectLogic(logic).toFinishAllListeners()
            const readsAtCap = statusReads.length

            expect(readsAtCap).toBeGreaterThan(1)
            expect(logic.values.followedCredit).toBeNull()
            await jest.advanceTimersByTimeAsync(10_000)
            expect(statusReads).toHaveLength(readsAtCap)
        })
    })
})
