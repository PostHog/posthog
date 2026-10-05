import { dayjs } from 'lib/dayjs'
import { formatCurrency } from 'lib/utils/currency'
import { humanFriendlyCurrency } from 'lib/utils/numbers'
import { pluralize } from 'lib/utils/strings'

import { CurrencyCode } from '~/queries/schema/schema-general'

import type { PartnerPayerAddressApi, PartnerPayerSettlementApi, PartnerPayerTaxIdApi } from '../generated/api.schemas'

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

export function formatLimits(
    limits: Record<string, number | null> | undefined,
    productNames: Record<string, string>
): string | null {
    const setLimits = Object.entries(limits ?? {}).filter(
        (entry): entry is [string, number] => typeof entry[1] === 'number'
    )
    return setLimits.length > 0
        ? setLimits.map(([key, limit]) => `${productNames[key] ?? key} ${humanFriendlyCurrency(limit, 0)}`).join(', ')
        : null
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
