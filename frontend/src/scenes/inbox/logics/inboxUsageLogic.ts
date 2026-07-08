import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'

import { FEATURE_FLAGS } from 'lib/constants'
import { Dayjs } from 'lib/dayjs'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { calculateFreeTier } from 'scenes/billing/billing-utils'
import { billingLogic } from 'scenes/billing/billingLogic'
import { teamLogic } from 'scenes/teamLogic'

import { BillingProductV2Type } from '~/types'

import { signalsReportsRefundSummaryRetrieve } from 'products/signals/frontend/generated/api'
import type { SignalReportRefundSummaryResponseApi } from 'products/signals/frontend/generated/api.schemas'

import { inboxBulkActionsLogic } from './inboxBulkActionsLogic'
import type { inboxUsageLogicType } from './inboxUsageLogicType'

// The inbox/signals billing product type (a flat per-PR credit charge). This is the identifier
// billing uses everywhere — it's also the key into `custom_limits_usd` — so we match on it rather
// than `usage_key` (the product reports usage under `signals_credits`).
const INBOX_PRODUCT_TYPE = 'inbox'

export type InboxUsageStatus = 'normal' | 'warning' | 'limit'

// Above this fraction of the limit we warn the user before they run out.
const WARNING_THRESHOLD = 0.8

/** Marginal USD price of a single credit, from the first paid tier (falling back to the product
 * unit price). Used with `creditsPerPr` to derive the per-PR price without hardcoding anything. */
function perCreditUsd(product: BillingProductV2Type): number | null {
    const paidTier = product.tiers?.find((tier) => parseFloat(tier.unit_amount_usd) > 0)
    if (paidTier) {
        return parseFloat(paidTier.unit_amount_usd)
    }
    return product.unit_amount_usd ? parseFloat(product.unit_amount_usd) : null
}

/**
 * Drives the PR-usage widget in the inbox agents rail. Reads the inbox/signals billing product and
 * surfaces usage, limit, and reset date in PRs (the product bills in credits; `display_divisor`
 * converts credits → PRs). Editing the limit writes a USD spend cap to `custom_limits_usd`, the
 * same mechanism the billing page uses.
 */
export const inboxUsageLogic = kea<inboxUsageLogicType>([
    path(['scenes', 'inbox', 'logics', 'inboxUsageLogic']),
    connect(() => ({
        values: [
            billingLogic,
            ['billing', 'billingLoading', 'canAccessBilling'],
            featureFlagLogic,
            ['featureFlags'],
            teamLogic,
            ['currentTeamId'],
        ],
        actions: [billingLogic, ['loadBilling', 'updateBillingLimits']],
    })),
    actions({
        openModal: true,
        closeModal: true,
    }),
    loaders(({ values }) => ({
        // Credited-path refund totals for the org's current billing period. Billing usage still
        // contains credited-refunded PRs (the money comes back as an invoice credit, not lower
        // usage), so the widget subtracts these to show the net PR count. Excluded-path refunds
        // never reach billing usage and need no adjustment.
        refundSummary: [
            null as SignalReportRefundSummaryResponseApi | null,
            {
                loadRefundSummary: async (): Promise<SignalReportRefundSummaryResponseApi | null> => {
                    if (!values.featureFlags[FEATURE_FLAGS.SIGNALS_PR_REFUNDS] || values.currentTeamId == null) {
                        return null
                    }
                    return await signalsReportsRefundSummaryRetrieve(String(values.currentTeamId))
                },
            },
        ],
    })),
    reducers({
        isModalOpen: [
            false,
            {
                openModal: () => true,
                closeModal: () => false,
                submitLimitFormSuccess: () => false,
            },
        ],
    }),
    // Defined before `selectors` so the `limitForm` values selector exists when
    // `estimatedBudgetUsd` lists it as an input (kea builds in array order).
    forms(({ actions, values }) => ({
        limitForm: {
            defaults: { prs: null as number | null },
            errors: ({ prs }) => ({
                prs:
                    prs == null
                        ? 'Enter a number of PRs'
                        : !Number.isInteger(prs) || prs < 0
                          ? 'Enter a whole number'
                          : prs < values.freePrs
                            ? `Minimum is ${values.freePrs} PRs (the free tier)`
                            : prs > 10000
                              ? 'Enter a smaller number'
                              : undefined,
            }),
            submit: ({ prs }) => {
                const { product, pricePerPrUsd, freePrs } = values
                if (!product || pricePerPrUsd == null || prs == null) {
                    return
                }
                const usd = Math.max(0, prs - freePrs) * pricePerPrUsd
                actions.updateBillingLimits({ [product.type]: usd })
            },
        },
    })),
    selectors({
        product: [
            (s) => [s.billing],
            (billing): BillingProductV2Type | null =>
                billing?.products?.find((p) => p.type === INBOX_PRODUCT_TYPE) ?? null,
        ],
        isLoading: [
            (s) => [s.billing, s.billingLoading, s.refundSummary, s.refundSummaryLoading, s.featureFlags],
            (billing, billingLoading, refundSummary, refundSummaryLoading, featureFlags): boolean => {
                if (billing === null && billingLoading) {
                    return true
                }
                // With refunds on, the PR count needs the refund summary too (live top-up +
                // credited netting) — rendering on billing alone briefly shows the gross number.
                return (
                    !!featureFlags[FEATURE_FLAGS.SIGNALS_PR_REFUNDS] && refundSummary === null && refundSummaryLoading
                )
            },
        ],
        // Free plan can't raise the limit past the free allocation — the widget points to
        // billing to upgrade instead of editing a limit.
        isSubscribed: [(s) => [s.product], (product): boolean => !!product?.subscribed],
        // Credits per PR — the API's credits → PR divisor. Null means we can't safely show PRs.
        creditsPerPr: [
            (s) => [s.product],
            (product): number | null =>
                product?.display_divisor && product.display_divisor > 0 ? product.display_divisor : null,
        ],
        pricePerPrUsd: [
            (s) => [s.product, s.creditsPerPr],
            (product, creditsPerPr): number | null => {
                if (!product || !creditsPerPr) {
                    return null
                }
                const perCredit = perCreditUsd(product)
                return perCredit != null ? perCredit * creditsPerPr : null
            },
        ],
        freePrs: [
            (s) => [s.product, s.creditsPerPr],
            (product, creditsPerPr): number =>
                product && creditsPerPr ? Math.round(calculateFreeTier(product) / creditsPerPr) : 0,
        ],
        usedPrs: [
            (s) => [s.product, s.creditsPerPr, s.refundSummary],
            (product, creditsPerPr, refundSummary): number => {
                if (!product || !creditsPerPr) {
                    return 0
                }
                // Billing's recorded usage lags by up to a day; the refund summary carries the org's
                // live billable credits, so take the max — a just-created PR counts immediately and a
                // same-day (excluded-path) refund visibly un-counts it.
                const billedCredits = Math.max(product.current_usage ?? 0, refundSummary?.period_billable_credits ?? 0)
                const billedPrs = Math.round(billedCredits / creditsPerPr)
                // Credited-path refunds stay in billing usage; net them out so the widget counts
                // only PRs the user is actually paying (or using free allowance) for.
                const refundedPrs = refundSummary ? Math.floor(refundSummary.credited_credits / creditsPerPr) : 0
                return Math.max(0, billedPrs - refundedPrs)
            },
        ],
        customLimitUsd: [
            (s) => [s.billing, s.product],
            (billing, product): number | null => {
                if (!product) {
                    return null
                }
                const limit = billing?.custom_limits_usd?.[product.type]
                return limit === 0 || limit ? Number(limit) : null
            },
        ],
        // The effective monthly PR cap: a user-set custom limit takes precedence, otherwise the
        // product's own usage_limit (credits). Null means uncapped.
        limitPrs: [
            (s) => [s.product, s.creditsPerPr, s.customLimitUsd, s.pricePerPrUsd, s.freePrs],
            (product, creditsPerPr, customLimitUsd, pricePerPrUsd, freePrs): number | null => {
                if (!product || !creditsPerPr) {
                    return null
                }
                if (customLimitUsd != null && pricePerPrUsd) {
                    return freePrs + Math.round(customLimitUsd / pricePerPrUsd)
                }
                if (product.usage_limit != null) {
                    return Math.round(product.usage_limit / creditsPerPr)
                }
                return null
            },
        ],
        status: [
            (s) => [s.usedPrs, s.limitPrs],
            (usedPrs, limitPrs): InboxUsageStatus => {
                if (limitPrs == null) {
                    return 'normal'
                }
                if (usedPrs >= limitPrs) {
                    return 'limit'
                }
                if (usedPrs / limitPrs >= WARNING_THRESHOLD) {
                    return 'warning'
                }
                return 'normal'
            },
        ],
        // Displayed usage caps at the limit — we never show "53 / 50" when usage runs over.
        usedPrsDisplay: [
            (s) => [s.usedPrs, s.limitPrs],
            (usedPrs, limitPrs): number => (limitPrs != null ? Math.min(usedPrs, limitPrs) : usedPrs),
        ],
        // USD spent so far this period: PRs beyond the free allowance, at the per-PR price.
        // Null when we can't price a PR (so the widget hides the figure rather than show "$0").
        spentUsd: [
            (s) => [s.usedPrs, s.freePrs, s.pricePerPrUsd],
            (usedPrs, freePrs, pricePerPrUsd): number | null =>
                pricePerPrUsd == null ? null : Math.max(0, usedPrs - freePrs) * pricePerPrUsd,
        ],
        // Bar fill as a % of the denominator (the limit, or the free allowance when uncapped).
        percentage: [
            (s) => [s.usedPrs, s.limitPrs, s.freePrs],
            (usedPrs, limitPrs, freePrs): number => {
                const denominator = limitPrs ?? (freePrs || null)
                if (!denominator) {
                    return 0
                }
                return Math.min(100, Math.round((usedPrs / denominator) * 100))
            },
        ],
        resetDate: [(s) => [s.billing], (billing): Dayjs | null => billing?.billing_period?.current_period_end ?? null],
        // USD spend cap implied by the limit currently typed into the modal. Drives the live budget.
        estimatedBudgetUsd: [
            (s) => [s.limitForm, s.pricePerPrUsd, s.freePrs],
            (limitForm, pricePerPrUsd, freePrs): number | null => {
                const prs = limitForm?.prs
                if (pricePerPrUsd == null || prs == null || Number.isNaN(prs)) {
                    return null
                }
                return Math.max(0, prs - freePrs) * pricePerPrUsd
            },
        ],
    }),
    listeners(({ actions, values }) => ({
        openModal: () => {
            // Seed the field with the current limit (or the free allowance when uncapped).
            actions.setLimitFormValue('prs', values.limitPrs ?? values.freePrs)
        },
        // Refunds broadcast `reportArchived` after archiving server-side; reload the summary so
        // the widget's netted PR count updates in-session (mirrors the reportListLogic reconcile
        // listener — a plain archive just makes this a cheap no-op reload).
        [inboxBulkActionsLogic.actionTypes.reportArchived]: () => actions.loadRefundSummary(),
    })),
    afterMount(({ actions, values }) => {
        if (!values.billing) {
            actions.loadBilling()
        }
        actions.loadRefundSummary()
    }),
])
