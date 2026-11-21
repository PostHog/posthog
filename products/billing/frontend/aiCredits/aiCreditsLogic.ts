import {
    MakeLogicType,
    actions,
    afterMount,
    connect,
    isBreakpoint,
    kea,
    listeners,
    path,
    reducers,
    selectors,
} from 'kea'
import { forms } from 'kea-forms'
import type { DeepPartial, DeepPartialMap, FieldName, ValidationErrorType } from 'kea-forms'
import { loaders } from 'kea-loaders'
import posthog from 'posthog-js'
import { z } from 'zod'

import { lemonToast } from '@posthog/lemon-ui'

import { ApiError } from 'lib/api-error'
import { dayjs } from 'lib/dayjs'
import { uuid } from 'lib/utils/dom'
import { LocalStorageSlot, localStorageSlot } from 'lib/utils/localStorageSlot'
import { humanFriendlyCurrency } from 'lib/utils/numbers'
import { organizationLogic } from 'scenes/organizationLogic'

import {
    billingAiCreditsCardRetrieve,
    billingAiCreditsHistoryRetrieve,
    billingAiCreditsPurchaseCreate,
    billingAiCreditsPurchaseRetrieve,
    billingAiCreditsQuoteRetrieve,
    billingAiCreditsSettingsAutomaticReloadPartialUpdate,
    billingAiCreditsSettingsRetrieve,
    billingAiCreditsSettingsSpendLimitPartialUpdate,
    billingAiCreditsSpendLimitRetrieve,
    billingAiCreditsSpendRetrieve,
} from 'products/billing/frontend/generated/api'
import type {
    AICreditCardApi,
    AICreditCardResponseApi,
    AICreditHistoryResponseApi,
    AICreditPurchaseResponseApi,
    AICreditPurchaseStatusResponseApi,
    AICreditQuoteResponseApi,
    AICreditSettingsResponseApi,
    AISpendLimitResponseApi,
    AISpendResponseApi,
    PatchedAIAutomaticReloadRequestApi,
} from 'products/billing/frontend/generated/api.schemas'

import type { OrganizationType } from '../../../../frontend/src/types'
import {
    AISpendSummary,
    BILLING_PERIODS_SHOWN,
    BillingPeriodOption,
    billingPeriodOptions,
    ChartedProduct,
    chartedProducts,
    reloadedSince,
    summarizeSpend,
} from './aiSpend'

export const AI_CREDIT_PRESET_AMOUNTS_USD = [20, 50, 100]
export const MINIMUM_AI_CREDIT_USD = 20
export const MAXIMUM_AI_CREDIT_USD = 1_000_000
const HISTORY_PAGE_SIZE = 50
// Billing answers processing only after its own wait, so fast first reads catch an answer that follows soon.
const STATUS_READ_FAST_INTERVAL_MS = 2000
// The fast reads stop this long after the reads start, so a slow payment does not cost many reads.
const STATUS_READ_FAST_PERIOD_MS = 10_000
// After the fast reads, each read waits at least this long, to keep the load on billing low.
const STATUS_READ_SLOW_MIN_INTERVAL_MS = 5000
// Each later read waits a random time up to this long, so that many waiting pages do not read at the same moment.
const STATUS_READ_SLOW_MAX_INTERVAL_MS = 10_000
// Reads stop this long after the person pays or billing answers paid, so a page left open stops calling billing.
const STATUS_READ_CAP_MS = 120_000

const PURCHASE_FAILED = "The purchase didn't finish. Try again."
const STRIPE_UNAVAILABLE = "We couldn't load the payment form. Disable any ad blocker, reload the page and try again."
const CARD_NOT_AUTHENTICATED = "Your card's authentication didn't finish, so you weren't charged. Try again."
const CREDIT_PENDING = 'Payment received. Your AI credits show as pending until we add them to your balance.'
const CREDIT_ADDED = 'Payment received. We added your AI credits to your balance.'
// Each of these ends the purchase without a charge, so paying again starts a new purchase.
const PURCHASE_ENDING_CODES = [
    'ai_credits_card_declined',
    'ai_credits_purchase_ended',
    'ai_credits_total_changed',
    'ai_credits_purchase_not_found',
]

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
        ? `up to ${humanFriendlyCurrency(amounts.monthlyReloadLimitUsd)} of credit each billing period, plus tax`
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

function isSet(value: number | null | undefined): value is number {
    return value !== undefined && value !== null
}

function reloadTargetError(threshold: number | null, target: number | null): string | undefined {
    if (!isSet(target)) {
        return 'Enter the balance to reload to'
    }
    if (isSet(threshold) && target - threshold < MINIMUM_AI_CREDIT_USD) {
        return `Reload to at least $${MINIMUM_AI_CREDIT_USD} more than the low balance`
    }
    return target > MAXIMUM_AI_CREDIT_USD ? 'Reload to at most $1,000,000' : undefined
}

function reloadAmountErrors(amounts: ReloadAmounts): Partial<Record<keyof ReloadAmounts, string>> {
    const { lowBalanceThresholdUsd: threshold, targetUsd: target, monthlyReloadLimitUsd: limit } = amounts
    return {
        lowBalanceThresholdUsd: !isSet(threshold) || threshold < 0 ? 'Enter a balance of $0 or more' : undefined,
        targetUsd: reloadTargetError(threshold, target),
        monthlyReloadLimitUsd:
            isSet(limit) && limit < MINIMUM_AI_CREDIT_USD
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

// The AI gateway doesn't report spend everywhere yet, so a failed read leaves the spend out
// instead of showing an error on every visit.
async function readSpend(periodsAgo: number): Promise<AISpendResponseApi | null> {
    try {
        return await billingAiCreditsSpendRetrieve({ periods_ago: periodsAgo })
    } catch {
        return null
    }
}

/** Null when the AI gateway didn't answer, so a settings save knows to leave the limit alone. */
async function readSpendLimit(): Promise<AISpendLimitResponseApi | null> {
    try {
        return await billingAiCreditsSpendLimitRetrieve()
    } catch {
        return null
    }
}

/** A purchase that billing hasn't given a final answer. Billing derives the Stripe idempotency keys from its key. */
export interface UnansweredPurchase {
    key: string
    amountUsd: string
    totalUsd: string
    /** When the person last paid. The page stops the status reads STATUS_READ_CAP_MS after this. */
    startedAt: number
    /** The organization the page paid for. Each status read names it, also after a switch in another tab. */
    organizationId: string
    /** The automatic reload that the person chose with the purchase. The page turns it on once billing answers paid. */
    reload: ReloadAmounts | null
}

/**
 * Processing while the page reads the status on a schedule, still processing after the read cap, and authenticating
 * while Stripe.js runs the card authentication. Each of them keeps the pay button disabled.
 */
export type PurchaseStatus = 'processing' | 'still_processing' | 'authenticating'

/** The page reads the status only while billing processes the purchase, never while Stripe.js authenticates it. */
function awaitsAnswer(status: PurchaseStatus | null): boolean {
    return status === 'processing' || status === 'still_processing'
}

export type PurchaseAnswer =
    | { kind: 'processing' }
    | { kind: 'requires_action'; clientSecret: string | null }
    | { kind: 'paid'; creditAdded: boolean }
    | { kind: 'failed'; failure: PurchaseFailure }

/** A paid purchase whose status the page reads until billing adds its credit to the balance. */
export interface FollowedCredit {
    key: string
    organizationId: string
    startedAt: number
}

export interface PurchaseFailure {
    code: string | null
    message: string
    /** Billing charged nothing, so paying again needs a new idempotency key. */
    endsPurchase: boolean
}

function purchaseFailure(error: unknown): PurchaseFailure {
    const code = error instanceof ApiError ? (error.code ?? null) : null
    return {
        code,
        message: error instanceof PaymentNotConfirmed ? error.message : errorMessage(error, PURCHASE_FAILED),
        endsPurchase: !!code && PURCHASE_ENDING_CODES.includes(code),
    }
}

function reloadAmounts(form: ReloadAmounts): ReloadAmounts {
    return {
        lowBalanceThresholdUsd: form.lowBalanceThresholdUsd ?? null,
        targetUsd: form.targetUsd ?? null,
        monthlyReloadLimitUsd: form.monthlyReloadLimitUsd ?? null,
    }
}

const storedPurchaseSchema = z.object({
    key: z.string(),
    amountUsd: z.string(),
    totalUsd: z.string(),
    startedAt: z.number(),
    organizationId: z.string(),
    reload: z
        .object({
            lowBalanceThresholdUsd: z.number().nullable(),
            targetUsd: z.number().nullable(),
            monthlyReloadLimitUsd: z.number().nullable(),
        })
        .nullable(),
})

// Each organization has its own key, so a purchase resumes only on the page of the organization that paid.
function storedPurchaseKey(organizationId: string): string {
    return `ai-credits-unanswered-purchase-${organizationId}`
}

/** The purchase that billing still processes, kept so that a reload or another tab can follow it to its answer. */
function storedPurchase(organizationId: string): LocalStorageSlot<UnansweredPurchase> {
    return localStorageSlot(storedPurchaseKey(organizationId), storedPurchaseSchema)
}

function forgetStoredPurchase(organizationId: string): void {
    try {
        localStorage.removeItem(storedPurchaseKey(organizationId))
    } catch {
        // Storage that the browser does not make available holds no purchase.
    }
}

/** How long to wait before the next status read, from how long the page has read the status. */
function statusReadDelayMs(readingForMs: number): number {
    if (readingForMs < STATUS_READ_FAST_PERIOD_MS) {
        return STATUS_READ_FAST_INTERVAL_MS
    }
    const spread = STATUS_READ_SLOW_MAX_INTERVAL_MS - STATUS_READ_SLOW_MIN_INTERVAL_MS
    return STATUS_READ_SLOW_MIN_INTERVAL_MS + Math.random() * spread
}

async function turnOnReloadAfterPurchase(
    organizationId: string,
    card: AICreditCardApi,
    reload: ReloadAmounts,
    totalUsd: string
): Promise<void> {
    try {
        await billingAiCreditsSettingsAutomaticReloadPartialUpdate({
            organization_id: organizationId,
            ...reloadRequest(reload),
            enabled: true,
            consent_text: automaticReloadConsent(card, reload, totalUsd),
        })
    } catch (error) {
        lemonToast.error(
            `Your payment went through, but automatic reload didn't turn on. ${errorMessage(error, 'Turn it on in the settings.')}`
        )
    }
}

const SETTINGS_NOT_SAVED = "We couldn't save these settings. Try again."

function settingsSaveError(error: unknown): string {
    if (error instanceof ApiError) {
        return errorMessage(error, SETTINGS_NOT_SAVED)
    }
    return error instanceof Error ? error.message : SETTINGS_NOT_SAVED
}

async function saveReloadSettings(
    organizationId: string,
    form: AISpendSettingsForm,
    reload: AICreditSettingsResponseApi['automatic_reload'] | undefined,
    card: AICreditCardApi | null | undefined
): Promise<void> {
    const turningOn = form.reloadEnabled && !reload?.enabled
    if (turningOn && !card) {
        throw new Error('Add a card to your billing details before you turn on automatic reload.')
    }
    // Only turning reload on needs the card, because the consent names it. A save while reload is on keeps
    // working when the card didn't load.
    if (form.reloadEnabled) {
        await billingAiCreditsSettingsAutomaticReloadPartialUpdate({
            organization_id: organizationId,
            ...reloadRequest(form),
            ...(turningOn && card ? { enabled: true, consent_text: automaticReloadConsent(card, form) } : {}),
        })
    } else if (reload?.enabled) {
        await billingAiCreditsSettingsAutomaticReloadPartialUpdate({ organization_id: organizationId, enabled: false })
    }
}

/** Runs the card authentication that billing's payment asks for, such as a 3D Secure check. */
async function confirmCardAuthentication(clientSecret: string | null): Promise<void> {
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
        throw new PaymentNotConfirmed(CARD_NOT_AUTHENTICATED)
    }
}

function purchaseAnswer(answer: AICreditPurchaseResponseApi | AICreditPurchaseStatusResponseApi): PurchaseAnswer {
    if (answer.status === 'processing') {
        return { kind: 'processing' }
    }
    if (answer.status === 'requires_action') {
        return { kind: 'requires_action', clientSecret: answer.client_secret ?? null }
    }
    return { kind: 'paid', creditAdded: 'credit_status' in answer && answer.credit_status === 'added' }
}

/**
 * Sends the purchase to billing once. The same key reaches the same purchase, so billing charges the card at most
 * once however often the page sends it.
 */
async function sendPurchase(purchase: UnansweredPurchase): Promise<PurchaseAnswer> {
    try {
        return purchaseAnswer(
            await billingAiCreditsPurchaseCreate({
                organization_id: purchase.organizationId,
                amount_usd: purchase.amountUsd,
                total_usd: purchase.totalUsd,
                idempotency_key: purchase.key,
            })
        )
    } catch (error) {
        return { kind: 'failed', failure: purchaseFailure(error) }
    }
}

/** Reads billing's answer for a purchase as it stands. The read starts nothing and charges nothing. */
async function readPurchase(organizationId: string, key: string): Promise<PurchaseAnswer> {
    try {
        return purchaseAnswer(await billingAiCreditsPurchaseRetrieve(key, { organization_id: organizationId }))
    } catch (error) {
        // A read that billing or the network did not answer says nothing new, so the page reads again later.
        const unanswered =
            !(error instanceof ApiError) || error.status === undefined || error.status >= 500 || error.status === 429
        return unanswered ? { kind: 'processing' } : { kind: 'failed', failure: purchaseFailure(error) }
    }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface aiCreditsLogicValues {
    currentOrganization: OrganizationType | null // organizationLogic
    currentOrganizationId: string // organizationLogic
    addFundsConsent: string | null
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
    currentSpend: AISpendResponseApi | null
    currentSpendLoading: boolean
    currentSpendSummary: AISpendSummary | null
    currentSpendUnavailable: boolean
    followedCredit: FollowedCredit | null
    history: AICreditHistoryResponseApi | null
    historyLoading: boolean
    isAddFundsFormSubmitting: boolean
    isAddFundsFormValid: boolean
    isCurrentPeriod: boolean
    isSpendSettingsFormSubmitting: boolean
    isSpendSettingsFormValid: boolean
    pageOrganizationId: string
    pastSpend: AISpendResponseApi | null
    pastSpendLoading: boolean
    pastSpendPeriodsAgo: number | null
    payDisabledReason: string | null
    pendingUsd: number
    periodOptions: BillingPeriodOption[]
    previousSpend: AISpendResponseApi | null
    previousSpendLoading: boolean
    previousSpendPeriodsAgo: number | null
    purchaseError: string | null
    purchasePending: boolean
    purchaseStatus: PurchaseStatus | null
    quote: AICreditQuoteResponseApi | null
    quoteError: string | null
    quoteLoading: boolean
    recordedOrganizationId: string | null
    reloadedThisPeriodText: string | null
    reloadedThisPeriodUsd: number | null
    selectedPeriodsAgo: number
    settings: AICreditSettingsResponseApi | null
    settingsEditDisabledReason: string | null
    settingsLoading: boolean
    settingsModalOpen: boolean
    showAddFundsFormErrors: boolean
    showSpendSettingsFormErrors: boolean
    spend: AISpendResponseApi | null
    spendLimit: AISpendLimitResponseApi | null
    spendLimitLoading: boolean
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
    statusReadsStartedAt: number | null
    unansweredPurchase: UnansweredPurchase | null
    unavailable: boolean
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface aiCreditsLogicActions {
    authenticationStarted: () => {
        value: true
    }
    checkPendingPurchase: () => {
        value: true
    }
    closeAddFundsModal: () => {
        value: true
    }
    closeSettingsModal: () => {
        value: true
    }
    creditAdded: () => {
        value: true
    }
    followCredit: (credit: FollowedCredit) => {
        credit: FollowedCredit
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
    loadCurrentSpend: () => any
    loadCurrentSpendFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadCurrentSpendSuccess: (
        currentSpend: AISpendResponseApi | null,
        payload?: any
    ) => {
        currentSpend: AISpendResponseApi | null
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
    loadPastSpend: (periodsAgo: number) => number
    loadPastSpendFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadPastSpendSuccess: (
        pastSpend: AISpendResponseApi | null,
        payload?: number
    ) => {
        pastSpend: AISpendResponseApi | null
        payload?: number
    }
    loadPreviousSpend: (periodsAgo: number) => number
    loadPreviousSpendFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadPreviousSpendSuccess: (
        previousSpend: AISpendResponseApi | null,
        payload?: number
    ) => {
        previousSpend: AISpendResponseApi | null
        payload?: number
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
    loadSpendLimit: () => any
    loadSpendLimitFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadSpendLimitSuccess: (
        spendLimit: AISpendLimitResponseApi | null,
        payload?: any
    ) => {
        spendLimit: AISpendLimitResponseApi | null
        payload?: any
    }
    openAddFundsModal: () => {
        value: true
    }
    openSettingsModal: () => {
        value: true
    }
    purchaseAnswered: (
        answer: PurchaseAnswer,
        authenticated?: boolean
    ) => {
        answer: PurchaseAnswer
        authenticated: boolean
    }
    purchaseCompleted: (
        purchase: UnansweredPurchase,
        authenticated: boolean,
        creditAdded: boolean
    ) => {
        authenticated: boolean
        creditAdded: boolean
        purchase: UnansweredPurchase
    }
    purchaseFailed: (
        failure: PurchaseFailure,
        authenticated: boolean
    ) => {
        authenticated: boolean
        failure: PurchaseFailure
    }
    purchaseProcessing: (readsStartedAt: number) => {
        readsStartedAt: number
    }
    purchaseResumed: (
        purchase: UnansweredPurchase,
        status: PurchaseStatus
    ) => {
        purchase: UnansweredPurchase
        status: PurchaseStatus
    }
    purchaseTimedOut: () => {
        value: true
    }
    readCreditStatus: () => {
        value: true
    }
    readPurchaseStatus: () => {
        value: true
    }
    recordPageOrganization: (organizationId: string | null) => {
        organizationId: string | null
    }
    resetAddFundsForm: (values?: AddFundsForm) => {
        values?: AddFundsForm
    }
    resetSpendSettingsForm: (values?: AISpendSettingsForm) => {
        values?: AISpendSettingsForm
    }
    selectPeriod: (periodsAgo: number) => {
        periodsAgo: number
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
    setUnansweredPurchase: (purchase: UnansweredPurchase | null) => {
        purchase: UnansweredPurchase | null
    }
    stopFollowingCredit: () => {
        value: true
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
        pageOrganizationId: (recordedOrganizationId: string | null, currentOrganizationId: string) => string
        isCurrentPeriod: (selectedPeriodsAgo: number) => boolean
        purchasePending: (purchaseStatus: PurchaseStatus | null) => boolean
        payDisabledReason: (
            purchaseStatus: PurchaseStatus | null,
            card: AICreditCardResponseApi | null,
            quote: AICreditQuoteResponseApi | null
        ) => string | null
        spend: (
            selectedPeriodsAgo: number,
            currentSpend: AISpendResponseApi | null,
            pastSpend: AISpendResponseApi | null,
            pastSpendPeriodsAgo: number | null
        ) => AISpendResponseApi | null
        spendUnavailable: (
            selectedPeriodsAgo: number,
            currentSpendUnavailable: boolean,
            pastSpend: AISpendResponseApi | null,
            pastSpendPeriodsAgo: number | null
        ) => boolean
        spendSummary: (
            spend: AISpendResponseApi | null,
            previousSpend: AISpendResponseApi | null,
            previousSpendPeriodsAgo: number | null,
            selectedPeriodsAgo: number
        ) => AISpendSummary | null
        currentSpendSummary: (currentSpend: AISpendResponseApi | null) => AISpendSummary | null
        periodOptions: (currentSpend: AISpendResponseApi | null) => BillingPeriodOption[]
        spendProducts: (spend: AISpendResponseApi | null) => ChartedProduct[]
        pendingUsd: (history: AICreditHistoryResponseApi | null) => number
        reloadedThisPeriodUsd: (
            history: AICreditHistoryResponseApi | null,
            currentSpend: AISpendResponseApi | null
        ) => number | null
        addFundsConsent: (
            card: AICreditCardResponseApi | null,
            quote: AICreditQuoteResponseApi | null,
            addFundsForm: AddFundsForm,
            settings: AICreditSettingsResponseApi | null
        ) => string | null
        reloadedThisPeriodText: (
            reloadedThisPeriodUsd: number | null,
            settings: AICreditSettingsResponseApi | null
        ) => string | null
        settingsEditDisabledReason: (
            settings: AICreditSettingsResponseApi | null,
            settingsLoading: boolean,
            spendLimitLoading: boolean
        ) => string | null
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
    // Every purchase, save and quote names the organization the page loaded for. A person can switch organization in
    // another tab. This tab can then reload the current organization, so the page records the organization when it
    // mounts. It sends the live value only when the organization had not loaded by then.
    connect(() => ({ values: [organizationLogic, ['currentOrganization', 'currentOrganizationId']] })),
    actions({
        openAddFundsModal: true,
        closeAddFundsModal: true,
        openSettingsModal: true,
        closeSettingsModal: true,
        setUnansweredPurchase: (purchase: UnansweredPurchase | null) => ({ purchase }),
        setPurchaseError: (error: string | null) => ({ error }),
        purchaseAnswered: (answer: PurchaseAnswer, authenticated: boolean = false) => ({ answer, authenticated }),
        checkPendingPurchase: true,
        purchaseResumed: (purchase: UnansweredPurchase, status: PurchaseStatus) => ({ purchase, status }),
        readPurchaseStatus: true,
        purchaseProcessing: (readsStartedAt: number) => ({ readsStartedAt }),
        purchaseTimedOut: true,
        authenticationStarted: true,
        purchaseFailed: (failure: PurchaseFailure, authenticated: boolean) => ({ failure, authenticated }),
        purchaseCompleted: (purchase: UnansweredPurchase, authenticated: boolean, creditAdded: boolean) => ({
            purchase,
            authenticated,
            creditAdded,
        }),
        followCredit: (credit: FollowedCredit) => ({ credit }),
        readCreditStatus: true,
        creditAdded: true,
        stopFollowingCredit: true,
        loadQuote: (amountUsd: number | null) => ({ amountUsd }),
        setQuote: (quote: AICreditQuoteResponseApi | null) => ({ quote }),
        setQuoteError: (error: string) => ({ error }),
        selectPeriod: (periodsAgo: number) => ({ periodsAgo }),
        recordPageOrganization: (organizationId: string | null) => ({ organizationId }),
    }),
    loaders(({ values }) => ({
        settings: [
            null as AICreditSettingsResponseApi | null,
            { loadSettings: async () => await billingAiCreditsSettingsRetrieve() },
        ],
        card: [null as AICreditCardResponseApi | null, { loadCard: async () => await billingAiCreditsCardRetrieve() }],
        spendLimit: [null as AISpendLimitResponseApi | null, { loadSpendLimit: async () => await readSpendLimit() }],
        // The current period carries the balance, the reloads and the limit, whichever period the page shows.
        currentSpend: [null as AISpendResponseApi | null, { loadCurrentSpend: async () => await readSpend(0) }],
        pastSpend: [
            null as AISpendResponseApi | null,
            {
                loadPastSpend: async (periodsAgo: number, breakpoint) => {
                    const spend = await readSpend(periodsAgo)
                    breakpoint()
                    return spend
                },
            },
        ],
        // The period before the one shown, to compare the daily average with.
        previousSpend: [
            null as AISpendResponseApi | null,
            {
                loadPreviousSpend: async (periodsAgo: number, breakpoint) => {
                    const spend = await readSpend(periodsAgo + 1)
                    breakpoint()
                    return spend
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
                    return { ...current, results: [...current.results, ...older.results], has_more: older.has_more }
                },
            },
        ],
    })),
    reducers({
        recordedOrganizationId: [
            null as string | null,
            { recordPageOrganization: (_, { organizationId }) => organizationId },
        ],
        addFundsModalOpen: [false, { openAddFundsModal: () => true, closeAddFundsModal: () => false }],
        settingsModalOpen: [false, { openSettingsModal: () => true, closeSettingsModal: () => false }],
        // One key per purchase the person pays for. Every send of that purchase reuses it, so billing charges the
        // card at most once. The key stays until billing gives a final answer, also when the person closes the
        // modal or the quote reloads.
        unansweredPurchase: [
            null as UnansweredPurchase | null,
            {
                setUnansweredPurchase: (_, { purchase }) => purchase,
                purchaseResumed: (_, { purchase }) => purchase,
                purchaseCompleted: () => null,
                purchaseFailed: (purchase, { failure }) => (failure.endsPurchase ? null : purchase),
            },
        ],
        purchaseStatus: [
            null as PurchaseStatus | null,
            {
                purchaseResumed: (_, { status }) => status,
                purchaseProcessing: () => 'processing',
                purchaseTimedOut: () => 'still_processing',
                authenticationStarted: () => 'authenticating',
                purchaseCompleted: () => null,
                purchaseFailed: () => null,
            },
        ],
        // When the page started to read the status of the processing purchase, for the fast reads at the start.
        statusReadsStartedAt: [
            null as number | null,
            {
                purchaseProcessing: (_, { readsStartedAt }) => readsStartedAt,
                purchaseResumed: () => null,
                purchaseTimedOut: () => null,
                authenticationStarted: () => null,
                purchaseCompleted: () => null,
                purchaseFailed: () => null,
            },
        ],
        followedCredit: [
            null as FollowedCredit | null,
            { followCredit: (_, { credit }) => credit, creditAdded: () => null, stopFollowingCredit: () => null },
        ],
        purchaseError: [
            null as string | null,
            { setPurchaseError: (_, { error }) => error, openAddFundsModal: () => null, loadQuote: () => null },
        ],
        quote: [null as AICreditQuoteResponseApi | null, { loadQuote: () => null, setQuote: (_, { quote }) => quote }],
        quoteLoading: [false, { loadQuote: () => true, setQuote: () => false, setQuoteError: () => false }],
        quoteError: [null as string | null, { loadQuote: () => null, setQuoteError: (_, { error }) => error }],
        selectedPeriodsAgo: [0, { selectPeriod: (_, { periodsAgo }) => periodsAgo }],
        currentSpendUnavailable: [false, { loadCurrentSpendSuccess: (_, { currentSpend }) => currentSpend === null }],
        // Which period each read answered, so the page never shows a read for another period.
        pastSpendPeriodsAgo: [null as number | null, { loadPastSpendSuccess: (_, { payload }) => payload ?? null }],
        previousSpendPeriodsAgo: [
            null as number | null,
            { loadPreviousSpendSuccess: (_, { payload }) => payload ?? null },
        ],
        unavailable: [
            false,
            {
                loadCardSuccess: () => false,
                loadCardFailure: (_, { errorObject }) =>
                    errorObject instanceof ApiError && errorObject.code === 'ai_credits_unavailable',
            },
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
                // The form also submits on Enter, so the disabled pay button alone can't stop a second purchase.
                if (values.purchasePending) {
                    return
                }
                if (!quote || !card) {
                    actions.setPurchaseError('Wait for the total, then pay.')
                    return
                }
                // Another amount is another purchase, so it gets a new key.
                const unanswered = values.unansweredPurchase
                const purchase: UnansweredPurchase = {
                    key: unanswered?.amountUsd === quote.amount_usd ? unanswered.key : uuid(),
                    amountUsd: quote.amount_usd,
                    totalUsd: quote.total_usd,
                    startedAt: Date.now(),
                    organizationId: values.pageOrganizationId,
                    reload:
                        form.reloadEnabled && !values.settings?.automatic_reload.enabled ? reloadAmounts(form) : null,
                }
                actions.setUnansweredPurchase(purchase)
                actions.setPurchaseError(null)
                actions.purchaseAnswered(await sendPurchase(purchase))
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
                spendLimitUsd:
                    form.noSpendLimit || !values.spendLimit
                        ? undefined
                        : form.spendLimitUsd === undefined || form.spendLimitUsd === null
                          ? 'Enter a limit, or choose no limit'
                          : form.spendLimitUsd < 0
                            ? 'Enter a limit of $0 or more'
                            : undefined,
            }),
            submit: async (form: AISpendSettingsForm) => {
                const settings = values.settings
                try {
                    await saveReloadSettings(
                        values.pageOrganizationId,
                        form,
                        settings?.automatic_reload,
                        values.card?.card
                    )
                    // The form only knows the limit once the AI gateway answered, so it leaves an unknown limit alone.
                    const spendLimit = form.noSpendLimit ? null : usd(form.spendLimitUsd)
                    if (values.spendLimit && spendLimit !== values.spendLimit.limit_usd) {
                        await billingAiCreditsSettingsSpendLimitPartialUpdate({
                            organization_id: values.pageOrganizationId,
                            limit_usd: spendLimit,
                        })
                    }
                } catch (error) {
                    lemonToast.error(settingsSaveError(error))
                    actions.loadSettings()
                    actions.loadSpendLimit()
                    return
                }
                posthog.capture('ai credits settings saved', {
                    automatic_reload: form.reloadEnabled,
                    has_spend_limit: !form.noSpendLimit,
                })
                lemonToast.success('AI credit settings saved')
                actions.closeSettingsModal()
                actions.loadSettings()
                actions.loadSpendLimit()
            },
        },
    })),
    selectors({
        pageOrganizationId: [
            (s) => [s.recordedOrganizationId, s.currentOrganizationId],
            (recordedOrganizationId: string | null, currentOrganizationId: string): string =>
                recordedOrganizationId ?? currentOrganizationId,
        ],
        isCurrentPeriod: [(s) => [s.selectedPeriodsAgo], (periodsAgo: number): boolean => periodsAgo === 0],
        purchasePending: [(s) => [s.purchaseStatus], (status: PurchaseStatus | null): boolean => status !== null],
        payDisabledReason: [
            (s) => [s.purchaseStatus, s.card, s.quote],
            (
                status: PurchaseStatus | null,
                card: AICreditCardResponseApi | null,
                quote: AICreditQuoteResponseApi | null
            ): string | null => {
                if (status === 'still_processing') {
                    return "We're still confirming your last payment"
                }
                if (status) {
                    return 'The payment is in progress'
                }
                if (!card?.card) {
                    return 'Add a card to your billing details first'
                }
                return quote ? null : 'Wait for the total'
            },
        ],
        spend: [
            (s) => [s.selectedPeriodsAgo, s.currentSpend, s.pastSpend, s.pastSpendPeriodsAgo],
            (
                periodsAgo: number,
                currentSpend: AISpendResponseApi | null,
                pastSpend: AISpendResponseApi | null,
                pastSpendPeriodsAgo: number | null
            ): AISpendResponseApi | null =>
                periodsAgo === 0 ? currentSpend : pastSpendPeriodsAgo === periodsAgo ? pastSpend : null,
        ],
        spendUnavailable: [
            (s) => [s.selectedPeriodsAgo, s.currentSpendUnavailable, s.pastSpend, s.pastSpendPeriodsAgo],
            (
                periodsAgo: number,
                currentSpendUnavailable: boolean,
                pastSpend: AISpendResponseApi | null,
                pastSpendPeriodsAgo: number | null
            ): boolean =>
                periodsAgo === 0 ? currentSpendUnavailable : pastSpendPeriodsAgo === periodsAgo && pastSpend === null,
        ],
        spendSummary: [
            (s) => [s.spend, s.previousSpend, s.previousSpendPeriodsAgo, s.selectedPeriodsAgo],
            (
                spend: AISpendResponseApi | null,
                previousSpend: AISpendResponseApi | null,
                previousSpendPeriodsAgo: number | null,
                periodsAgo: number
            ): AISpendSummary | null =>
                spend
                    ? summarizeSpend(spend, previousSpendPeriodsAgo === periodsAgo ? previousSpend : null, dayjs())
                    : null,
        ],
        currentSpendSummary: [
            (s) => [s.currentSpend],
            (currentSpend: AISpendResponseApi | null): AISpendSummary | null =>
                currentSpend ? summarizeSpend(currentSpend, null, dayjs()) : null,
        ],
        periodOptions: [
            (s) => [s.currentSpend],
            (currentSpend: AISpendResponseApi | null): BillingPeriodOption[] =>
                currentSpend
                    ? billingPeriodOptions(currentSpend.period_start, currentSpend.period_end, BILLING_PERIODS_SHOWN)
                    : [],
        ],
        spendProducts: [
            (s) => [s.spend],
            (spend: AISpendResponseApi | null): ChartedProduct[] => (spend ? chartedProducts(spend) : []),
        ],
        pendingUsd: [
            (s) => [s.history],
            (history: AICreditHistoryResponseApi | null): number =>
                (history?.results ?? [])
                    .filter((entry) => entry.status === 'pending')
                    .reduce((sum, entry) => sum + Number(entry.amount_usd), 0),
        ],
        reloadedThisPeriodUsd: [
            (s) => [s.history, s.currentSpend],
            (history: AICreditHistoryResponseApi | null, currentSpend: AISpendResponseApi | null): number | null =>
                currentSpend ? reloadedSince(history, currentSpend.period_start) : null,
        ],
        addFundsConsent: [
            (s) => [s.card, s.quote, s.addFundsForm, s.settings],
            (
                card: AICreditCardResponseApi | null,
                quote: AICreditQuoteResponseApi | null,
                form: AddFundsForm,
                settings: AICreditSettingsResponseApi | null
            ): string | null => {
                if (!card?.card || !quote) {
                    return null
                }
                return form.reloadEnabled && !settings?.automatic_reload.enabled
                    ? automaticReloadConsent(card.card, form, quote.total_usd)
                    : purchaseConsent(card.card, quote.total_usd)
            },
        ],
        reloadedThisPeriodText: [
            (s) => [s.reloadedThisPeriodUsd, s.settings],
            (reloadedUsd: number | null, settings: AICreditSettingsResponseApi | null): string | null => {
                const limit = settings?.automatic_reload.monthly_reload_limit_usd
                if (reloadedUsd === null) {
                    return null
                }
                return limit
                    ? `${settingAmount(reloadedUsd)} of ${settingAmount(limit)} reloaded this period`
                    : `${settingAmount(reloadedUsd)} reloaded this period`
            },
        ],
        // The settings form starts from the saved settings, so the person edits them only after they load.
        settingsEditDisabledReason: [
            (s) => [s.settings, s.settingsLoading, s.spendLimitLoading],
            (
                settings: AICreditSettingsResponseApi | null,
                settingsLoading: boolean,
                spendLimitLoading: boolean
            ): string | null => {
                if (settingsLoading || spendLimitLoading) {
                    return 'Loading your settings'
                }
                return settings ? null : "Your settings didn't load. Reload the page."
            },
        ],
    }),
    listeners(({ actions, values, cache }) => {
        // Each kind of read has one timer. A new timer with the same key replaces the old one, and unmounting the
        // page disposes it. The last wait ends at the cap, so the read that stops the reads comes at the cap.
        const scheduleRead = (timerKey: string, read: () => void, readsStartedAt: number, cappedFrom: number): void => {
            cache.disposables.add(() => {
                const untilCap = Math.max(cappedFrom + STATUS_READ_CAP_MS - Date.now(), 0)
                const wait = Math.min(statusReadDelayMs(Date.now() - readsStartedAt), untilCap)
                const timerId = window.setTimeout(read, wait)
                return () => window.clearTimeout(timerId)
            }, timerKey)
        }

        return {
            loadQuote: async ({ amountUsd }, breakpoint) => {
                await breakpoint(300)
                if (!amountUsd || amountUsd < MINIMUM_AI_CREDIT_USD || amountUsd > MAXIMUM_AI_CREDIT_USD) {
                    actions.setQuote(null)
                    return
                }
                try {
                    const quote = await billingAiCreditsQuoteRetrieve({
                        organization_id: values.pageOrganizationId,
                        amount_usd: amountUsd.toFixed(2),
                    })
                    breakpoint()
                    actions.setQuote(quote)
                } catch (error) {
                    if (isBreakpoint(error as Error)) {
                        throw error
                    }
                    // A newer quote replaced this one, so its failure must not show over the newer state.
                    breakpoint()
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
                    spendLimitUsd: amount(values.spendLimit?.limit_usd),
                    noSpendLimit: !values.spendLimit?.limit_usd,
                })
            },
            loadCurrentSpendSuccess: ({ currentSpend }) => {
                if (currentSpend && values.selectedPeriodsAgo === 0) {
                    actions.loadPreviousSpend(0)
                }
            },
            selectPeriod: ({ periodsAgo }) => {
                if (periodsAgo > 0) {
                    actions.loadPastSpend(periodsAgo)
                }
                actions.loadPreviousSpend(periodsAgo)
                posthog.capture('ai credits period selected', { periods_ago: periodsAgo })
            },
            checkPendingPurchase: () => {
                const organizationId = values.recordedOrganizationId ?? values.currentOrganization?.id
                if (!organizationId || values.isAddFundsFormSubmitting || values.purchaseStatus === 'authenticating') {
                    return
                }
                const current = values.unansweredPurchase
                if (!current) {
                    const stored = storedPurchase(organizationId).get()
                    if (!stored || stored.organizationId !== organizationId) {
                        return
                    }
                    const withinCap = Date.now() - stored.startedAt < STATUS_READ_CAP_MS
                    actions.purchaseResumed(stored, withinCap ? 'processing' : 'still_processing')
                } else if (!values.purchasePending) {
                    return
                }
                actions.readPurchaseStatus()
            },
            readPurchaseStatus: async (_, breakpoint) => {
                const purchase = values.unansweredPurchase
                if (!purchase || !awaitsAnswer(values.purchaseStatus)) {
                    return
                }
                const answer = await readPurchase(purchase.organizationId, purchase.key)
                breakpoint()
                // Another answer can end the purchase, or start its authentication, while this read runs.
                if (
                    cache.disposables.isDisposed ||
                    values.unansweredPurchase?.key !== purchase.key ||
                    !awaitsAnswer(values.purchaseStatus)
                ) {
                    return
                }
                actions.purchaseAnswered(answer)
            },
            purchaseAnswered: async ({ answer, authenticated }) => {
                const purchase = values.unansweredPurchase
                if (!purchase) {
                    return
                }
                if (answer.kind === 'processing') {
                    if (values.purchaseStatus === null) {
                        storedPurchase(purchase.organizationId).set(purchase)
                        actions.loadHistory()
                    }
                    if (Date.now() - purchase.startedAt >= STATUS_READ_CAP_MS) {
                        cache.disposables.dispose('purchaseStatusRead')
                        actions.purchaseTimedOut()
                        return
                    }
                    const readsStartedAt = values.statusReadsStartedAt ?? Date.now()
                    actions.purchaseProcessing(readsStartedAt)
                    scheduleRead(
                        'purchaseStatusRead',
                        () => actions.readPurchaseStatus(),
                        readsStartedAt,
                        purchase.startedAt
                    )
                    return
                }
                cache.disposables.dispose('purchaseStatusRead')
                if (answer.kind === 'requires_action') {
                    actions.authenticationStarted()
                    let next: PurchaseAnswer = { kind: 'paid', creditAdded: false }
                    try {
                        await confirmCardAuthentication(answer.clientSecret)
                    } catch (error) {
                        next = { kind: 'failed', failure: purchaseFailure(error) }
                    }
                    if (!cache.disposables.isDisposed) {
                        actions.purchaseAnswered(next, true)
                    }
                    return
                }
                // A final answer. A purchase that ends here must not resume in a reload or in another tab.
                forgetStoredPurchase(purchase.organizationId)
                if (answer.kind === 'failed') {
                    if (values.purchaseStatus !== null) {
                        actions.loadHistory()
                    }
                    actions.purchaseFailed(answer.failure, authenticated)
                    return
                }
                const card = values.card?.card
                if (purchase.reload && card && !values.settings?.automatic_reload.enabled) {
                    await turnOnReloadAfterPurchase(purchase.organizationId, card, purchase.reload, purchase.totalUsd)
                }
                actions.purchaseCompleted(purchase, authenticated, answer.creditAdded)
            },
            purchaseFailed: ({ failure, authenticated }) => {
                if (failure.code === 'ai_credits_total_changed') {
                    actions.loadQuote(values.addFundsForm.amountUsd)
                }
                // The quote load clears the error, so this listener sets the error after it.
                actions.setPurchaseError(failure.message)
                // The person may have closed the modal while billing still processed the purchase.
                if (!values.addFundsModalOpen) {
                    lemonToast.error(failure.message)
                }
                posthog.capture('ai credits purchase failed', { code: failure.code, authenticated })
            },
            purchaseCompleted: ({ purchase, authenticated, creditAdded }) => {
                posthog.capture('ai credits purchase completed', {
                    amount_usd: Number(purchase.amountUsd),
                    authenticated,
                })
                lemonToast.success(creditAdded ? CREDIT_ADDED : CREDIT_PENDING)
                actions.closeAddFundsModal()
                if (!creditAdded) {
                    actions.followCredit({
                        key: purchase.key,
                        organizationId: purchase.organizationId,
                        startedAt: Date.now(),
                    })
                }
                actions.loadHistory()
                actions.loadSettings()
                actions.loadCurrentSpend()
            },
            followCredit: ({ credit }) => {
                scheduleRead('creditStatusRead', () => actions.readCreditStatus(), credit.startedAt, credit.startedAt)
            },
            readCreditStatus: async (_, breakpoint) => {
                const credit = values.followedCredit
                if (!credit) {
                    return
                }
                const answer = await readPurchase(credit.organizationId, credit.key)
                breakpoint()
                if (cache.disposables.isDisposed || values.followedCredit?.key !== credit.key) {
                    return
                }
                if (answer.kind === 'paid' && answer.creditAdded) {
                    actions.creditAdded()
                    return
                }
                if (answer.kind === 'failed') {
                    actions.stopFollowingCredit()
                    lemonToast.error(answer.failure.message)
                    return
                }
                // The history keeps the credit as pending until the next visit to the page.
                if (Date.now() - credit.startedAt >= STATUS_READ_CAP_MS) {
                    actions.stopFollowingCredit()
                    return
                }
                // After a card authentication, billing can answer requires_action or processing until Stripe tells it
                // about the payment. Both mean that the credit is not added yet.
                scheduleRead('creditStatusRead', () => actions.readCreditStatus(), credit.startedAt, credit.startedAt)
            },
            creditAdded: () => {
                cache.disposables.dispose('creditStatusRead')
                actions.loadHistory()
                actions.loadCurrentSpend()
            },
            stopFollowingCredit: () => {
                cache.disposables.dispose('creditStatusRead')
            },
        }
    }),
    afterMount(({ actions, values, cache }) => {
        actions.recordPageOrganization(values.currentOrganization?.id ?? null)
        actions.loadSettings()
        actions.loadSpendLimit()
        actions.loadCard()
        actions.loadHistory()
        actions.loadCurrentSpend()
        actions.checkPendingPurchase()
        // A hidden page gets no focus, and a paused listener could miss the focus that comes as the page shows again.
        cache.disposables.add(
            () => {
                const onFocus = (): void => actions.checkPendingPurchase()
                window.addEventListener('focus', onFocus)
                return () => window.removeEventListener('focus', onFocus)
            },
            'pendingPurchaseFocusCheck',
            { pauseOnPageHidden: false }
        )
    }),
])
