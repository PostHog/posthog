import { billingProductDisplayName } from 'scenes/billing/billingProductDisplayName'

import type { BillingProductV2Type } from '~/types'

import type { PartnerPayerStatusApi, PatchedPartnerPayerAdminUpdateApi } from '../generated/api.schemas'

export interface PartnerBillingLimitProduct {
    key: string
    name: string
}

/** Monthly limit in whole US dollars per product key. A missing or null value means no limit. */
export type PartnerBillingLimitValues = Record<string, number | null>

export interface PartnerBillingWebhookFormValues {
    webhook_url: string
}

export interface PartnerBillingSpendingFormValues {
    spend_alert_usd: string
    spend_cap_usd: string
    default_limits_usd: PartnerBillingLimitValues
}

const DOLLAR_AMOUNT_PATTERN = /^\d{1,10}(\.\d{1,2})?$/

export function limitCatalogFromBillingProducts(products: BillingProductV2Type[]): PartnerBillingLimitProduct[] {
    return products
        .filter((product) => !!product.usage_key)
        .map((product) => ({ key: product.type, name: billingProductDisplayName(product) }))
}

export function limitProductsFor(
    catalog: PartnerBillingLimitProduct[],
    limits: PartnerBillingLimitValues
): PartnerBillingLimitProduct[] {
    const catalogKeys = new Set(catalog.map((product) => product.key))
    const productsMissingFromCatalog = Object.keys(limits)
        .filter((key) => !catalogKeys.has(key))
        .map((key) => ({ key, name: key }))
    return [...catalog, ...productsMissingFromCatalog]
}

export function limitFormValues(limits: Record<string, number | null> | undefined): PartnerBillingLimitValues {
    return Object.fromEntries(Object.entries(limits ?? {}).filter(([, value]) => typeof value === 'number'))
}

/** The limits to send: each product whose limit changed, with null where the limit was cleared. */
export function limitChanges(
    saved: Record<string, number | null> | undefined,
    edited: PartnerBillingLimitValues
): Record<string, number | null> {
    const changes: Record<string, number | null> = {}
    for (const key of new Set([...Object.keys(saved ?? {}), ...Object.keys(edited)])) {
        const savedLimit = saved?.[key] ?? null
        const editedLimit = edited[key] ?? null
        if (savedLimit !== editedLimit) {
            changes[key] = editedLimit
        }
    }
    return changes
}

export function limitErrors(limits: PartnerBillingLimitValues): Record<string, string | undefined> {
    return Object.fromEntries(
        Object.entries(limits).map(([key, limit]) => [
            key,
            limit == null || (Number.isInteger(limit) && limit >= 0)
                ? undefined
                : 'Enter a whole number of dollars, 0 or more.',
        ])
    )
}

export function webhookFormValues(payer: PartnerPayerStatusApi | null): PartnerBillingWebhookFormValues {
    return { webhook_url: payer?.webhook?.url ?? '' }
}

export function webhookChanges(
    payer: PartnerPayerStatusApi | null,
    form: PartnerBillingWebhookFormValues
): PatchedPartnerPayerAdminUpdateApi {
    const webhookUrl = form.webhook_url.trim()
    return webhookUrl === (payer?.webhook?.url ?? '') ? {} : { webhook_url: webhookUrl || null }
}

export function webhookUrlError(webhookUrl: string): string | undefined {
    const trimmed = webhookUrl.trim()
    if (!trimmed) {
        return undefined
    }
    try {
        return new URL(trimmed).protocol === 'https:' ? undefined : 'Enter an HTTPS URL.'
    } catch {
        return 'Enter an HTTPS URL.'
    }
}

export function spendingFormValues(payer: PartnerPayerStatusApi | null): PartnerBillingSpendingFormValues {
    return {
        spend_alert_usd: payer?.spend?.alert_usd ?? '',
        spend_cap_usd: payer?.spend?.cap_usd ?? '',
        default_limits_usd: limitFormValues(payer?.default_limits_usd),
    }
}

export function spendingChanges(
    payer: PartnerPayerStatusApi | null,
    form: PartnerBillingSpendingFormValues
): PatchedPartnerPayerAdminUpdateApi {
    const changes: PatchedPartnerPayerAdminUpdateApi = {}
    const spendAlert = form.spend_alert_usd.trim()
    if (spendAlert !== (payer?.spend?.alert_usd ?? '')) {
        changes.spend_alert_usd = spendAlert || null
    }
    const spendCap = form.spend_cap_usd.trim()
    if (spendCap !== (payer?.spend?.cap_usd ?? '')) {
        changes.spend_cap_usd = spendCap || null
    }
    const defaultLimits = limitChanges(payer?.default_limits_usd, form.default_limits_usd)
    if (Object.keys(defaultLimits).length > 0) {
        changes.default_limits_usd = defaultLimits
    }
    return changes
}

export function dollarAmountError(amount: string): string | undefined {
    const trimmed = amount.trim()
    return !trimmed || DOLLAR_AMOUNT_PATTERN.test(trimmed) ? undefined : 'Enter an amount like 1000 or 1000.50.'
}
