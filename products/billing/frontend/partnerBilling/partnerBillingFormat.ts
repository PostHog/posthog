import { dayjs } from 'lib/dayjs'
import { formatCurrency } from 'lib/utils/currency'
import { humanFriendlyCurrency } from 'lib/utils/numbers'
import { pluralize } from 'lib/utils/strings'

import { CurrencyCode } from '~/queries/schema/schema-general'

import type { PartnerPayerAddressApi, PartnerPayerSettlementApi, PartnerPayerTaxIdApi } from '../generated/api.schemas'
import { limitFormValues } from './partnerBillingForms'

export function formatAmountCents(amountCents: number, currency: string | undefined): string {
    return formatCurrency(amountCents / 100, (currency ?? 'usd').toUpperCase() as CurrencyCode)
}

// A period that starts at midnight UTC would show the previous day in local time west of UTC.
export function formatBillingPeriod(start: string | null | undefined, end: string | null | undefined): string | null {
    if (!start || !end) {
        return null
    }
    const startDate = dayjs.utc(start)
    const endDate = dayjs.utc(end)
    const startFormat = startDate.year() === endDate.year() ? 'MMM D' : 'MMM D, YYYY'
    return `${startDate.format(startFormat)} to ${endDate.format('MMM D, YYYY')}`
}

export function formatAddress(address: PartnerPayerAddressApi | null | undefined): string | null {
    if (!address) {
        return null
    }
    const region = [address.state, address.postal_code].filter(Boolean).join(' ')
    const parts = [address.line1, address.line2, address.city, region, address.country].filter(Boolean)
    return parts.length > 0 ? parts.join(', ') : null
}

export interface PartnerBillingAppliedLimit {
    productKey: string
    label: string
}

// An organization's own limit replaces the partner's default for that product. An own limit of null means no
// limit at all, so that product does not fall back to the default.
export function formatAppliedLimits(
    ownLimits: Record<string, number | null> | undefined,
    defaultLimits: Record<string, number | null> | undefined,
    productNames: Record<string, string>
): PartnerBillingAppliedLimit[] {
    const own = ownLimits ?? {}
    const defaults = limitFormValues(defaultLimits)
    const catalogOrder = Object.keys(productNames)
    const position = (productKey: string): number =>
        catalogOrder.includes(productKey) ? catalogOrder.indexOf(productKey) : catalogOrder.length
    return [...new Set([...Object.keys(defaults), ...Object.keys(own)])]
        .sort((a, b) => position(a) - position(b))
        .map((productKey) => {
            const ownLimit = own[productKey]
            const limit = !(productKey in own)
                ? `Default ${humanFriendlyCurrency(defaults[productKey], 0)}`
                : typeof ownLimit === 'number'
                  ? humanFriendlyCurrency(ownLimit, 0)
                  : 'No limit'
            return { productKey, label: `${productNames[productKey] ?? productKey}: ${limit}` }
        })
}

export function formatTaxId(taxId: PartnerPayerTaxIdApi): string {
    const type = taxId.type ? taxId.type.replace(/_/g, ' ').toUpperCase() : null
    return [type, taxId.value].filter(Boolean).join(' ')
}

export function formatSettlementCharge(settlement: PartnerPayerSettlementApi): string | null {
    if (settlement.paid_at) {
        return `Paid ${dayjs(settlement.paid_at).format('MMM D, YYYY')}`
    }
    if (settlement.next_attempt_at) {
        return `Next attempt ${dayjs(settlement.next_attempt_at).format('MMM D, YYYY')}`
    }
    if (settlement.attempt_count) {
        return `Tried ${pluralize(settlement.attempt_count, 'time')}`
    }
    return null
}
