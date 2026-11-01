import { MakeLogicType, actions, afterMount, isBreakpoint, kea, listeners, path, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import type { DeepPartial, DeepPartialMap, FieldName, ValidationErrorType } from 'kea-forms'
import { loaders } from 'kea-loaders'
import posthog from 'posthog-js'

import { lemonToast } from '@posthog/lemon-ui'

import { ApiError } from 'lib/api-error'
import { dayjs } from 'lib/dayjs'
import { uuid } from 'lib/utils/dom'
import { humanFriendlyCurrency } from 'lib/utils/numbers'

import {
    billingAiCreditsCardRetrieve,
    billingAiCreditsHistoryRetrieve,
    billingAiCreditsPurchaseCreate,
    billingAiCreditsQuoteRetrieve,
    billingAiCreditsSettingsAutomaticReloadPartialUpdate,
    billingAiCreditsSettingsRetrieve,
    billingAiCreditsSettingsSpendLimitPartialUpdate,
    billingAiCreditsSpendRetrieve,
} from 'products/billing/frontend/generated/api'
import type {
    AICreditCardApi,
    AICreditCardResponseApi,
    AICreditHistoryResponseApi,
    AICreditQuoteResponseApi,
    AICreditSettingsResponseApi,
    AISpendResponseApi,
    PatchedAIAutomaticReloadRequestApi,
} from 'products/billing/frontend/generated/api.schemas'

import { AISpendSummary, ChartedProduct, chartedProducts, reloadedSince, summarizeSpend } from './aiSpend'

export const AI_CREDIT_PRESET_AMOUNTS_USD = [20, 50, 100]
export const MINIMUM_AI_CREDIT_USD = 20
export const MAXIMUM_AI_CREDIT_USD = 1_000_000
const HISTORY_PAGE_SIZE = 50

const PURCHASE_FAILED = "The purchase didn't finish. Try again."
const STRIPE_UNAVAILABLE = "We couldn't load the payment form. Disable any ad blocker, reload the page and try again."
const BANK_DID_NOT_CONFIRM = "Your bank didn't confirm the payment, so you weren't charged. Try again."
// Each of these ends the purchase without a charge, so paying again starts a new purchase.
const PURCHASE_ENDING_CODES = ['ai_credits_card_declined', 'ai_credits_purchase_ended', 'ai_credits_total_changed']

// Number inputs clear to undefined at runtime, so the code checks for both null and undefined.
export interface ReloadAmounts {
    lowBalanceThresholdUsd: number | null
    targetUsd: number | null
    monthlyReloadLimitUsd: number | null
}

export interface AddFundsForm extends ReloadAmounts {
    amountUsd: number | null
    // The person chose "Other" and types the amount.
    customAmount: boolean
    reloadEnabled: boolean
}

export interface AISpendSettingsForm extends ReloadAmounts {
    reloadEnabled: boolean
    spendLimitUsd: number | null
    noSpendLimit: boolean
}

/** A setting's amount, such as "$20", with cents only when it has them. */
export function settingAmount(value: number | string): string {
    return Number.isInteger(Number(value)) ? humanFriendlyCurrency(value, 0) : humanFriendlyCurrency(value)
}

function cardBrand(card: AICreditCardApi): string {
    return card.brand.charAt(0).toUpperCase() + card.brand.slice(1)
}

export function cardLabel(card: AICreditCardApi): string {
    return `${cardBrand(card)} ending in ${card.last4}`
}

export function cardShortLabel(card: AICreditCardApi): string {
    return `${cardBrand(card)} ···· ${card.last4}`
}

/**
 * The words a person agrees to when they turn automatic reload on. Billing keeps them as the consent.
 * When they also pay now, the same sentence covers that charge.
 */
export function automaticReloadConsent(card: AICreditCardApi, amounts: ReloadAmounts, chargeNowUsd?: string): string {
    const limit = amounts.monthlyReloadLimitUsd
        ? `up to ${humanFriendlyCurrency(amounts.monthlyReloadLimitUsd)} each billing period`
        : 'with no limit each billing period'
    const now = chargeNowUsd ? ` ${humanFriendlyCurrency(chargeNowUsd)} now, and again` : ''
    return (
        `You authorize PostHog to charge your ${cardLabel(card)}${now} when your AI balance drops below ` +
        `${humanFriendlyCurrency(amounts.lowBalanceThresholdUsd ?? 0)}, to bring it back to ` +
        `${humanFriendlyCurrency(amounts.targetUsd ?? 0)}, ${limit}.`
    )
}

/** The words a person agrees to when they pay for credits without turning automatic reload on. */
export function purchaseConsent(card: AICreditCardApi, totalUsd: string): string {
    return `You authorize PostHog to charge your ${cardLabel(card)} ${humanFriendlyCurrency(totalUsd)} now.`
}

function usd(value: number | null | undefined): string | null {
    return value === undefined || value === null ? null : value.toFixed(2)
}

function reloadAmountErrors(amounts: ReloadAmounts): Partial<Record<keyof ReloadAmounts, string>> {
    const { lowBalanceThresholdUsd: threshold, targetUsd: target, monthlyReloadLimitUsd: limit } = amounts
    return {
        lowBalanceThresholdUsd:
            threshold === undefined || threshold === null || threshold < 0
                ? 'Enter a balance of $0 or more'
                : undefined,
        targetUsd:
            target === undefined || target === null
                ? 'Enter the balance to reload to'
                : threshold !== undefined && threshold !== null && target - threshold < MINIMUM_AI_CREDIT_USD
                  ? `Reload to at least $${MINIMUM_AI_CREDIT_USD} more than the low balance`
                  : target > MAXIMUM_AI_CREDIT_USD
                    ? 'Reload to at most $1,000,000'
                    : undefined,
        monthlyReloadLimitUsd:
            limit !== undefined && limit !== null && limit < MINIMUM_AI_CREDIT_USD
                ? `Set a limit of at least $${MINIMUM_AI_CREDIT_USD}, or leave it empty for no limit`
                : undefined,
    }
}

function reloadRequest(amounts: ReloadAmounts): PatchedAIAutomaticReloadRequestApi {
    return {
        low_balance_threshold_usd: usd(amounts.lowBalanceThresholdUsd),
        target_usd: usd(amounts.targetUsd),
        monthly_reload_limit_usd: usd(amounts.monthlyReloadLimitUsd),
    }
}

function errorMessage(error: unknown, fallback: string): string {
    return error instanceof ApiError && error.detail ? error.detail : fallback
}

class PaymentNotConfirmed extends Error {}

/** Lets the bank authenticate a payment that billing started, such as a 3D Secure check. */
async function confirmWithBank(clientSecret: string | null | undefined): Promise<void> {
    if (!clientSecret || !window.STRIPE_PUBLIC_KEY) {
        throw new PaymentNotConfirmed(STRIPE_UNAVAILABLE)
    }
    const { loadStripe } = await import('@stripe/stripe-js')
    const stripe = await loadStripe(window.STRIPE_PUBLIC_KEY)
    if (!stripe) {
        throw new PaymentNotConfirmed(STRIPE_UNAVAILABLE)
    }
    const { error, paymentIntent } = await stripe.handleNextAction({ clientSecret })
    if (error || !paymentIntent || !['succeeded', 'processing'].includes(paymentIntent.status)) {
        throw new PaymentNotConfirmed(BANK_DID_NOT_CONFIRM)
    }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface aiCreditsLogicValues {
    addFundsForm: AddFundsForm
    addFundsFormAllErrors: Record<string, any>
    addFundsFormChanged: boolean
    addFundsFormErrors: DeepPartialMap<AddFundsForm, ValidationErrorType>
    addFundsFormHasErrors: boolean
    addFundsFormManualErrors: Record<string, any>
    addFundsFormTouched: boolean
    addFundsFormTouches: Record<string, boolean>
    addFundsFormValidationErrors: DeepPartialMap<AddFundsForm, ValidationErrorType>
    addFundsModalOpen: boolean
    card: AICreditCardResponseApi | null
    cardLoading: boolean
    history: AICreditHistoryResponseApi | null
    historyLoading: boolean
    isAddFundsFormSubmitting: boolean
    isAddFundsFormValid: boolean
    isSpendSettingsFormSubmitting: boolean
    isSpendSettingsFormValid: boolean
    pendingUsd: number
    previousSpend: AISpendResponseApi | null
    previousSpendLoading: boolean
    purchaseError: string | null
    purchaseKey: string | null
    quote: AICreditQuoteResponseApi | null
    quoteError: string | null
    quoteLoading: boolean
    reloadedThisPeriodUsd: number | null
    settings: AICreditSettingsResponseApi | null
    settingsLoading: boolean
    settingsModalOpen: boolean
    showAddFundsFormErrors: boolean
    showSpendSettingsFormErrors: boolean
    spend: AISpendResponseApi | null
    spendLoading: boolean
    spendProducts: ChartedProduct[]
    spendSettingsForm: AISpendSettingsForm
    spendSettingsFormAllErrors: Record<string, any>
    spendSettingsFormChanged: boolean
    spendSettingsFormErrors: DeepPartialMap<AISpendSettingsForm, ValidationErrorType>
    spendSettingsFormHasErrors: boolean
    spendSettingsFormManualErrors: Record<string, any>
    spendSettingsFormTouched: boolean
    spendSettingsFormTouches: Record<string, boolean>
    spendSettingsFormValidationErrors: DeepPartialMap<AISpendSettingsForm, ValidationErrorType>
    spendSummary: AISpendSummary | null
    spendUnavailable: boolean
    unavailable: boolean
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface aiCreditsLogicActions {
    closeAddFundsModal: () => {
        value: true
    }
    closeSettingsModal: () => {
        value: true
    }
    loadCard: () => any
    loadCardFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadCardSuccess: (
        card: AICreditCardResponseApi,
        payload?: any
    ) => {
        card: AICreditCardResponseApi
        payload?: any
    }
    loadHistory: () => any
    loadHistoryFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadHistorySuccess: (
        history: AICreditHistoryResponseApi,
        payload?: any
    ) => {
        history: AICreditHistoryResponseApi
        payload?: any
    }
    loadOlderHistory: () => any
    loadOlderHistoryFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadOlderHistorySuccess: (
        history: AICreditHistoryResponseApi | null,
        payload?: any
    ) => {
        history: AICreditHistoryResponseApi | null
        payload?: any
    }
    loadPreviousSpend: () => any
    loadPreviousSpendFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadPreviousSpendSuccess: (
        previousSpend: AISpendResponseApi | null,
        payload?: any
    ) => {
        previousSpend: AISpendResponseApi | null
        payload?: any
    }
    loadQuote: (amountUsd: number | null) => {
        amountUsd: number | null
    }
    loadSettings: () => any
    loadSettingsFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadSettingsSuccess: (
        settings: AICreditSettingsResponseApi,
        payload?: any
    ) => {
        settings: AICreditSettingsResponseApi
        payload?: any
    }
    loadSpend: () => any
    loadSpendFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadSpendSuccess: (
        spend: AISpendResponseApi | null,
        payload?: any
    ) => {
        spend: AISpendResponseApi | null
        payload?: any
    }
    openAddFundsModal: () => {
        value: true
    }
    openSettingsModal: () => {
        value: true
    }
    purchaseCompleted: (
        amountUsd: number,
        authenticated: boolean
    ) => {
        amountUsd: number
        authenticated: boolean
    }
    resetAddFundsForm: (values?: AddFundsForm) => {
        values?: AddFundsForm
    }
    resetSpendSettingsForm: (values?: AISpendSettingsForm) => {
        values?: AISpendSettingsForm
    }
    setAddFundsFormManualErrors: (errors: Record<string, any>) => {
        errors: Record<string, any>
    }
    setAddFundsFormValue: (
        key: FieldName,
        value: any
    ) => {
        name: FieldName
        value: any
    }
    setAddFundsFormValues: (values: DeepPartial<AddFundsForm>) => {
        values: DeepPartial<AddFundsForm>
    }
    setPurchaseError: (error: string | null) => {
        error: string | null
    }
    setPurchaseKey: (key: string | null) => {
        key: string | null
    }
    setQuote: (quote: AICreditQuoteResponseApi | null) => {
        quote: AICreditQuoteResponseApi | null
    }
    setQuoteError: (error: string) => {
        error: string
    }
    setSpendSettingsFormManualErrors: (errors: Record<string, any>) => {
        errors: Record<string, any>
    }
    setSpendSettingsFormValue: (
        key: FieldName,
        value: any
    ) => {
        name: FieldName
        value: any
    }
    setSpendSettingsFormValues: (values: DeepPartial<AISpendSettingsForm>) => {
        values: DeepPartial<AISpendSettingsForm>
    }
    submitAddFundsForm: () => {
        value: boolean
    }
    submitAddFundsFormFailure: (
        error: Error,
        errors: Record<string, any>
    ) => {
        error: Error
        errors: Record<string, any>
    }
    submitAddFundsFormRequest: (addFundsForm: AddFundsForm) => {
        addFundsForm: AddFundsForm
    }
    submitAddFundsFormSuccess: (addFundsForm: AddFundsForm) => {
        addFundsForm: AddFundsForm
    }
    submitSpendSettingsForm: () => {
        value: boolean
    }
    submitSpendSettingsFormFailure: (
        error: Error,
        errors: Record<string, any>
    ) => {
        error: Error
        errors: Record<string, any>
    }
    submitSpendSettingsFormRequest: (spendSettingsForm: AISpendSettingsForm) => {
        spendSettingsForm: AISpendSettingsForm
    }
    submitSpendSettingsFormSuccess: (spendSettingsForm: AISpendSettingsForm) => {
        spendSettingsForm: AISpendSettingsForm
    }
    touchAddFundsFormField: (key: string) => {
        key: string
    }
    touchSpendSettingsFormField: (key: string) => {
        key: string
    }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface aiCreditsLogicMeta {
    __keaTypeGenInternalSelectorTypes: {
        spendSummary: (spend: any, previousSpend: any) => AISpendSummary | null
        spendProducts: (spend: any) => ChartedProduct[]
        pendingUsd: (history: AICreditHistoryResponseApi | null) => number
        reloadedThisPeriodUsd: (history: AICreditHistoryResponseApi | null, spend: any) => number | null
    }
}

export type aiCreditsLogicType = MakeLogicType<
    aiCreditsLogicValues,
    aiCreditsLogicActions,
    Record<string, any>,
    aiCreditsLogicMeta
>

export const aiCreditsLogic = kea<aiCreditsLogicType>([
    path(['products', 'billing', 'frontend', 'aiCredits', 'aiCreditsLogic']),
    actions({
        openAddFundsModal: true,
        closeAddFundsModal: true,
        openSettingsModal: true,
        closeSettingsModal: true,
        setPurchaseKey: (key: string | null) => ({ key }),
        setPurchaseError: (error: string | null) => ({ error }),
        purchaseCompleted: (amountUsd: number, authenticated: boolean) => ({ amountUsd, authenticated }),
        loadQuote: (amountUsd: number | null) => ({ amountUsd }),
        setQuote: (quote: AICreditQuoteResponseApi | null) => ({ quote }),
        setQuoteError: (error: string) => ({ error }),
    }),
    loaders(({ values }) => ({
        settings: [
            null as AICreditSettingsResponseApi | null,
            { loadSettings: async () => await billingAiCreditsSettingsRetrieve() },
        ],
        card: [null as AICreditCardResponseApi | null, { loadCard: async () => await billingAiCreditsCardRetrieve() }],
        // The AI gateway doesn't report spend everywhere yet, so a failed read leaves the spend out
        // instead of showing an error on every visit.
        spend: [
            null as AISpendResponseApi | null,
            {
                loadSpend: async () => {
                    try {
                        return await billingAiCreditsSpendRetrieve()
                    } catch {
                        return null
                    }
                },
            },
        ],
        previousSpend: [
            null as AISpendResponseApi | null,
            {
                loadPreviousSpend: async () => {
                    try {
                        return await billingAiCreditsSpendRetrieve({ period: 'previous' })
                    } catch {
                        return null
                    }
                },
            },
        ],
        history: [
            null as AICreditHistoryResponseApi | null,
            {
                loadHistory: async () => await billingAiCreditsHistoryRetrieve({ limit: HISTORY_PAGE_SIZE }),
                loadOlderHistory: async () => {
                    const current = values.history
                    if (!current?.has_more) {
                        return current
                    }
                    const older = await billingAiCreditsHistoryRetrieve({
                        limit: HISTORY_PAGE_SIZE,
                        offset: current.results.length,
                    })
                    return { results: [...current.results, ...older.results], has_more: older.has_more }
                },
            },
        ],
    })),
    reducers({
        addFundsModalOpen: [false, { openAddFundsModal: () => true, closeAddFundsModal: () => false }],
        settingsModalOpen: [false, { openSettingsModal: () => true, closeSettingsModal: () => false }],
        // One key per purchase the person confirms. A retry after billing didn't answer reuses it, so billing
        // charges the card at most once.
        purchaseKey: [
            null as string | null,
            { setPurchaseKey: (_, { key }) => key, openAddFundsModal: () => null, loadQuote: () => null },
        ],
        purchaseError: [
            null as string | null,
            { setPurchaseError: (_, { error }) => error, openAddFundsModal: () => null, loadQuote: () => null },
        ],
        quote: [null as AICreditQuoteResponseApi | null, { loadQuote: () => null, setQuote: (_, { quote }) => quote }],
        quoteLoading: [false, { loadQuote: () => true, setQuote: () => false, setQuoteError: () => false }],
        quoteError: [null as string | null, { loadQuote: () => null, setQuoteError: (_, { error }) => error }],
        spendUnavailable: [false, { loadSpendSuccess: (_, { spend }) => spend === null }],
        unavailable: [
            false,
            {
                loadCardSuccess: () => false,
                loadCardFailure: (_, { errorObject }) =>
                    errorObject instanceof ApiError && errorObject.code === 'ai_credits_unavailable',
            },
        ],
    }),
    selectors({
        spendSummary: [
            (s) => [s.spend, s.previousSpend],
            (spend, previousSpend): AISpendSummary | null =>
                spend ? summarizeSpend(spend, previousSpend, dayjs()) : null,
        ],
        spendProducts: [(s) => [s.spend], (spend): ChartedProduct[] => (spend ? chartedProducts(spend) : [])],
        pendingUsd: [
            (s) => [s.history],
            (history: AICreditHistoryResponseApi | null): number =>
                (history?.results ?? [])
                    .filter((entry) => entry.status === 'pending')
                    .reduce((sum, entry) => sum + Number(entry.amount_usd), 0),
        ],
        reloadedThisPeriodUsd: [
            (s) => [s.history, s.spend],
            (history: AICreditHistoryResponseApi | null, spend): number | null =>
                spend ? reloadedSince(history, spend.period_start) : null,
        ],
    }),
    forms(({ actions, values }) => ({
        addFundsForm: {
            defaults: {
                amountUsd: 50,
                customAmount: false,
                reloadEnabled: false,
                lowBalanceThresholdUsd: 20,
                targetUsd: 100,
                monthlyReloadLimitUsd: 300,
            } as AddFundsForm,
            errors: (form: AddFundsForm) => ({
                amountUsd:
                    !form.amountUsd || form.amountUsd < MINIMUM_AI_CREDIT_USD
                        ? `The minimum is $${MINIMUM_AI_CREDIT_USD}`
                        : form.amountUsd > MAXIMUM_AI_CREDIT_USD
                          ? 'The maximum is $1,000,000'
                          : undefined,
                ...(form.reloadEnabled ? reloadAmountErrors(form) : {}),
            }),
            submit: async (form: AddFundsForm) => {
                const quote = values.quote
                const card = values.card?.card
                if (!quote || !card) {
                    actions.setPurchaseError('Wait for the total, then pay.')
                    return
                }
                const key = values.purchaseKey ?? uuid()
                actions.setPurchaseKey(key)
                actions.setPurchaseError(null)
                let authenticated = false
                try {
                    const purchase = await billingAiCreditsPurchaseCreate({
                        amount_usd: quote.amount_usd,
                        total_usd: quote.total_usd,
                        idempotency_key: key,
                    })
                    if (purchase.status === 'requires_action') {
                        authenticated = true
                        await confirmWithBank(purchase.client_secret)
                    }
                } catch (error) {
                    const code = error instanceof ApiError ? error.code : null
                    if (code && PURCHASE_ENDING_CODES.includes(code)) {
                        actions.setPurchaseKey(null)
                    }
                    if (code === 'ai_credits_total_changed') {
                        actions.loadQuote(form.amountUsd)
                    }
                    actions.setPurchaseError(
                        error instanceof PaymentNotConfirmed ? error.message : errorMessage(error, PURCHASE_FAILED)
                    )
                    posthog.capture('ai credits purchase failed', { code, authenticated })
                    return
                }
                if (form.reloadEnabled && !values.settings?.automatic_reload.enabled) {
                    try {
                        await billingAiCreditsSettingsAutomaticReloadPartialUpdate({
                            ...reloadRequest(form),
                            enabled: true,
                            consent_text: automaticReloadConsent(card, form, quote.total_usd),
                        })
                    } catch (error) {
                        lemonToast.error(
                            `Your payment went through, but automatic reload didn't turn on. ${errorMessage(error, 'Turn it on in the settings.')}`
                        )
                    }
                }
                actions.purchaseCompleted(Number(quote.amount_usd), authenticated)
            },
        },
        spendSettingsForm: {
            defaults: {
                reloadEnabled: false,
                lowBalanceThresholdUsd: 20,
                targetUsd: 100,
                monthlyReloadLimitUsd: null,
                spendLimitUsd: null,
                noSpendLimit: true,
            } as AISpendSettingsForm,
            errors: (form: AISpendSettingsForm) => ({
                ...(form.reloadEnabled ? reloadAmountErrors(form) : {}),
                spendLimitUsd: form.noSpendLimit
                    ? undefined
                    : form.spendLimitUsd === undefined || form.spendLimitUsd === null
                      ? 'Enter a limit, or choose no limit'
                      : form.spendLimitUsd < 0
                        ? 'Enter a limit of $0 or more'
                        : undefined,
            }),
            submit: async (form: AISpendSettingsForm) => {
                const settings = values.settings
                const card = values.card?.card
                const reload = settings?.automatic_reload
                const turningOn = form.reloadEnabled && !reload?.enabled
                try {
                    if (turningOn && !card) {
                        throw new Error('Add a card to your billing details before you turn on automatic reload.')
                    }
                    if (form.reloadEnabled && card) {
                        await billingAiCreditsSettingsAutomaticReloadPartialUpdate({
                            ...reloadRequest(form),
                            ...(turningOn ? { enabled: true, consent_text: automaticReloadConsent(card, form) } : {}),
                        })
                    } else if (reload?.enabled) {
                        await billingAiCreditsSettingsAutomaticReloadPartialUpdate({ enabled: false })
                    }
                    const spendLimit = form.noSpendLimit ? null : usd(form.spendLimitUsd)
                    if (spendLimit !== (settings?.monthly_spend_limit_usd ?? null)) {
                        await billingAiCreditsSettingsSpendLimitPartialUpdate({ monthly_spend_limit_usd: spendLimit })
                    }
                } catch (error) {
                    lemonToast.error(
                        error instanceof ApiError
                            ? errorMessage(error, "We couldn't save these settings. Try again.")
                            : error instanceof Error
                              ? error.message
                              : "We couldn't save these settings. Try again."
                    )
                    actions.loadSettings()
                    return
                }
                posthog.capture('ai credits settings saved', {
                    automatic_reload: form.reloadEnabled,
                    has_spend_limit: !form.noSpendLimit,
                })
                lemonToast.success('AI credit settings saved')
                actions.closeSettingsModal()
                actions.loadSettings()
            },
        },
    })),
    listeners(({ actions, values }) => ({
        loadQuote: async ({ amountUsd }, breakpoint) => {
            await breakpoint(300)
            if (!amountUsd || amountUsd < MINIMUM_AI_CREDIT_USD || amountUsd > MAXIMUM_AI_CREDIT_USD) {
                actions.setQuote(null)
                return
            }
            try {
                const quote = await billingAiCreditsQuoteRetrieve({ amount_usd: amountUsd.toFixed(2) })
                breakpoint()
                actions.setQuote(quote)
            } catch (error) {
                if (isBreakpoint(error as Error)) {
                    throw error
                }
                actions.setQuoteError(errorMessage(error, "We couldn't work out the total. Try again in a minute."))
            }
        },
        openAddFundsModal: () => {
            actions.resetAddFundsForm()
            actions.loadCard()
            actions.loadQuote(values.addFundsForm.amountUsd)
            posthog.capture('ai credits add funds opened')
        },
        setAddFundsFormValue: ({ name }) => {
            if (name === 'amountUsd' || (Array.isArray(name) && name[0] === 'amountUsd')) {
                actions.loadQuote(values.addFundsForm.amountUsd)
            }
        },
        setAddFundsFormValues: ({ values: changed }) => {
            if ('amountUsd' in changed) {
                actions.loadQuote(values.addFundsForm.amountUsd)
            }
        },
        openSettingsModal: () => {
            const settings = values.settings
            const reload = settings?.automatic_reload
            const amount = (value: string | null | undefined): number | null =>
                value === null || value === undefined ? null : Number(value)
            actions.resetSpendSettingsForm({
                reloadEnabled: reload?.enabled ?? false,
                lowBalanceThresholdUsd: amount(settings?.low_balance_threshold_usd) ?? 20,
                targetUsd: amount(reload?.target_usd) ?? 100,
                monthlyReloadLimitUsd: amount(reload?.monthly_reload_limit_usd),
                spendLimitUsd: amount(settings?.monthly_spend_limit_usd),
                noSpendLimit: !settings?.monthly_spend_limit_usd,
            })
        },
        loadSpendSuccess: ({ spend }) => {
            if (spend) {
                actions.loadPreviousSpend()
            }
        },
        purchaseCompleted: ({ amountUsd, authenticated }) => {
            posthog.capture('ai credits purchase completed', { amount_usd: amountUsd, authenticated })
            lemonToast.success('Payment received. Your AI credits show as pending until they reach your balance.')
            actions.closeAddFundsModal()
            actions.loadHistory()
            actions.loadSettings()
            actions.loadSpend()
        },
    })),
    afterMount(({ actions }) => {
        actions.loadSettings()
        actions.loadCard()
        actions.loadHistory()
        actions.loadSpend()
    }),
])
