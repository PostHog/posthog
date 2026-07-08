import { BillingProductV2Type } from '~/types'

import {
    HOURS_PER_MONTH,
    calculateFreeTier,
    createGaugeItems,
    getSyntheticStorageAddon,
    isAlertOnlyProduct,
} from './billing-utils'
import { BillingGaugeItemKind } from './types'

const product = (overrides: Partial<BillingProductV2Type> = {}): BillingProductV2Type =>
    ({
        type: 'mobile_replay',
        subscribed: false,
        tiers: null,
        free_allocation: null,
        current_usage: 0,
        projected_usage: 0,
        usage_limit: null,
        percentage_usage: 0,
        addons: [],
        ...overrides,
    }) as unknown as BillingProductV2Type

const markerOf = (items: ReturnType<typeof createGaugeItems>): { text: string | JSX.Element; value: number } | null =>
    items.find((i) => i.type === BillingGaugeItemKind.BillingLimit) ?? null

describe('isAlertOnlyProduct', () => {
    it('prefers the billing API flag over the type fallback', () => {
        expect(isAlertOnlyProduct({ type: 'some_future_product', alert_only: true })).toBe(true)
        // API can explicitly override the hardcoded fallback list
        expect(isAlertOnlyProduct({ type: 'managed_data_warehouse_storage', alert_only: false })).toBe(false)
    })

    it('falls back to the type list when the API does not send the flag', () => {
        expect(isAlertOnlyProduct({ type: 'managed_data_warehouse_storage' })).toBe(true)
        expect(isAlertOnlyProduct({ type: 'mobile_replay' })).toBe(false)
    })
})

describe('createGaugeItems billing-limit marker', () => {
    it('does NOT leak a marker onto non-alert-only secondary variants from their usage_limit', () => {
        // Unsubscribed addons carry usage_limit = free_allocation — a marker defaulted from
        // usage_limit would show a spurious "Billing limit" on mobile replay et al.
        const items = createGaugeItems(product({ type: 'mobile_replay', usage_limit: 2500 }))
        expect(markerOf(items)).toBeNull()
    })

    it('shows a "Spend alert" marker for SUBSCRIBED alert-only products from their usage_limit', () => {
        const items = createGaugeItems(
            product({ type: 'managed_data_warehouse_storage', alert_only: true, subscribed: true, usage_limit: 130200 })
        )
        expect(markerOf(items)).toMatchObject({ text: 'Spend alert', value: 130200 })
    })

    it('does NOT show the alert marker for UNSUBSCRIBED alert-only products (usage_limit is the free allocation)', () => {
        const items = createGaugeItems(
            product({ type: 'managed_data_warehouse_storage', alert_only: true, subscribed: false, usage_limit: 74400 })
        )
        expect(markerOf(items)).toBeNull()
    })

    it('still shows an explicit "Billing limit" marker when the caller passes one', () => {
        const items = createGaugeItems(product({ type: 'mobile_replay' }), { billingLimitAsUsage: 5000 })
        expect(markerOf(items)).toMatchObject({ text: 'Billing limit', value: 5000 })
    })

    it('suppresses the marker for 100%-discount orgs when billing is provided', () => {
        const items = createGaugeItems(product({ type: 'mobile_replay' }), {
            billingLimitAsUsage: 5000,
            billing: { discount_percent: 100 } as any,
        })
        expect(markerOf(items)).toBeNull()
    })

    it('labels the storage free tier as a GB level (GB-hours / HOURS_PER_MONTH)', () => {
        const items = createGaugeItems(
            product({
                type: 'managed_data_warehouse_storage',
                subscribed: true,
                tiers: [{ unit_amount_usd: '0', up_to: 100 * HOURS_PER_MONTH } as any],
            })
        )
        const freeTier = items.find((i) => i.type === BillingGaugeItemKind.FreeTier)
        expect(freeTier).toMatchObject({ text: 'Free tier limit (100 GB)', value: 74400 })
    })
})

describe('calculateFreeTier', () => {
    it('uses the free tier boundary when subscribed, free_allocation otherwise', () => {
        expect(
            calculateFreeTier(product({ subscribed: true, tiers: [{ unit_amount_usd: '0', up_to: 74400 } as any] }))
        ).toBe(74400)
        expect(calculateFreeTier(product({ subscribed: false, free_allocation: 1000 }))).toBe(1000)
    })
})

describe('getSyntheticStorageAddon', () => {
    it('finds the display-nested storage product and nothing else', () => {
        const storage = { type: 'managed_data_warehouse_storage' }
        const withStorage = product({ addons: [{ type: 'mobile_replay' }, storage] as any })
        expect(getSyntheticStorageAddon(withStorage)).toBe(storage)
        expect(getSyntheticStorageAddon(product({ addons: [{ type: 'mobile_replay' }] as any }))).toBeUndefined()
    })
})
