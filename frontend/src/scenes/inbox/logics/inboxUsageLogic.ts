import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { Dayjs } from 'lib/dayjs'
import { toParams } from 'lib/utils/url'
import { calculateFreeTier } from 'scenes/billing/billing-utils'
import { billingLogic } from 'scenes/billing/billingLogic'
import type { BillingUsageResponse } from 'scenes/billing/billingUsageLogic'

import { BillingProductV2Type } from '~/types'

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
        values: [billingLogic, ['billing', 'billingLoading', 'canAccessBilling', 'billingPeriodUTC']],
        actions: [billingLogic, ['loadBilling', 'loadBillingSuccess', 'updateBillingLimits']],
    })),
    actions({
        openModal: true,
        closeModal: true,
    }),
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
    loaders(({ values }) => ({
        // Raw signals-credits usage for the current billing period, pulled from the v2 usage
        // endpoint. The billing product's `current_usage` omits usage before `billing_start_date`
        // on grandfathered plans — leaving only today's counter, which is why the widget appears to
        // reset daily. The raw usage timeseries has no such gap, so we sum it for the true total.
        signalsCreditsUsed: [
            null as number | null,
            {
                loadSignalsUsage: async () => {
                    // The usage endpoint requires org-admin (IsOrganizationAdmin); skip otherwise.
                    if (!values.canAccessBilling) {
                        return null
                    }
                    const { start, end } = values.billingPeriodUTC
                    if (!start || !end) {
                        return null
                    }
                    const params = {
                        usage_types: JSON.stringify(['signals_credits']),
                        start_date: start.format('YYYY-MM-DD'),
                        end_date: end.format('YYYY-MM-DD'),
                        interval: 'day',
                    }
                    const response: BillingUsageResponse = await api.get(`api/billing/usage/?${toParams(params)}`)
                    return (response?.results ?? []).reduce(
                        (total, series) => total + (series.data ?? []).reduce((sum, value) => sum + value, 0),
                        0
                    )
                },
            },
        ],
    })),
    selectors({
        product: [
            (s) => [s.billing],
            (billing): BillingProductV2Type | null =>
                billing?.products?.find((p) => p.type === INBOX_PRODUCT_TYPE) ?? null,
        ],
        isLoading: [
            (s) => [s.billing, s.billingLoading],
            (billing, billingLoading): boolean => billing === null && billingLoading,
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
            (s) => [s.product, s.creditsPerPr, s.signalsCreditsUsed],
            (product, creditsPerPr, signalsCreditsUsed): number => {
                if (!product || !creditsPerPr) {
                    return 0
                }
                // Prefer the raw period usage; fall back to the billing product's current_usage
                // when the usage endpoint is unavailable (e.g. non-admins, or still loading).
                const credits = signalsCreditsUsed ?? product.current_usage ?? 0
                return Math.round(credits / creditsPerPr)
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
        // The usage fetch needs the billing period, so wait until billing has loaded.
        loadBillingSuccess: () => {
            actions.loadSignalsUsage()
        },
    })),
    afterMount(({ actions, values }) => {
        if (!values.billing) {
            actions.loadBilling()
        } else {
            actions.loadSignalsUsage()
        }
    }),
])
