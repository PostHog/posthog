import type { CloudAgentRateCardApi, CloudAgentSizeApi } from '../generated/api.schemas'

type BoxDimensions = Pick<CloudAgentSizeApi, 'vcpu' | 'memory_gib'>

const MICRO_USD = 1_000_000

function toMicroUsd(value: string): number {
    return Math.round(Number.parseFloat(value) * MICRO_USD)
}

/** The price of one hour of a box, in millionths of a dollar. Integer math keeps the cents exact. */
function pricePerHourMicroUsd(size: BoxDimensions, rates: CloudAgentRateCardApi): number {
    return size.vcpu * toMicroUsd(rates.vcpu_hour_usd) + size.memory_gib * toMicroUsd(rates.memory_gib_hour_usd)
}

export function pricePerHourUsd(size: BoxDimensions, rates: CloudAgentRateCardApi): number {
    return pricePerHourMicroUsd(size, rates) / MICRO_USD
}

export function estimateComputeUsd(size: BoxDimensions, minutes: number, rates: CloudAgentRateCardApi): number {
    if (!Number.isFinite(minutes) || minutes <= 0) {
        return 0
    }
    return (pricePerHourMicroUsd(size, rates) * minutes) / 60 / MICRO_USD
}

/** An hourly price or a rate. Rates have three decimals, so this keeps them all. */
export function formatRate(value: string | number | null | undefined): string {
    const amount = typeof value === 'string' ? Number.parseFloat(value) : value
    if (amount === null || amount === undefined || !Number.isFinite(amount)) {
        return '-'
    }
    return `$${amount.toFixed(3)}`
}

/** A cost in dollars and cents. A cost below one cent shows as "<$0.01" and not as "$0.00". */
export function formatCost(value: string | number | null | undefined): string {
    const amount = typeof value === 'string' ? Number.parseFloat(value) : value
    if (amount === null || amount === undefined || !Number.isFinite(amount)) {
        return '-'
    }
    const cents = Math.round(amount * 100 + 1e-6)
    if (cents === 0 && amount > 0) {
        return '<$0.01'
    }
    return `$${(cents / 100).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

export function formatBoxSize(size: BoxDimensions): string {
    return `${size.vcpu} vCPU, ${size.memory_gib} GiB`
}

export function formatMinutes(minutes: number): string {
    return minutes === 1 ? '1 minute' : `${minutes} minutes`
}

/** The cost line under a box size select, for example "This box costs $0.368 per hour, about $0.09 for 15 minutes". */
export function describeBoxCost(size: BoxDimensions, minutes: number, rates: CloudAgentRateCardApi): string {
    return `This box costs ${formatRate(pricePerHourUsd(size, rates))} per hour, about ${formatCost(
        estimateComputeUsd(size, minutes, rates)
    )} for ${formatMinutes(minutes)}`
}

/** Usage arrives in vCPU-seconds and GiB-seconds, and the rate card is per hour. */
export function formatSecondsAsHours(seconds: string | number | null | undefined): string {
    const amount = typeof seconds === 'string' ? Number.parseFloat(seconds) : seconds
    if (amount === null || amount === undefined || !Number.isFinite(amount)) {
        return '-'
    }
    return (amount / 3600).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

export function formatSeconds(seconds: string | number | null | undefined): string {
    const amount = typeof seconds === 'string' ? Number.parseFloat(seconds) : seconds
    if (amount === null || amount === undefined || !Number.isFinite(amount)) {
        return '-'
    }
    return Math.round(amount).toLocaleString('en-US')
}
