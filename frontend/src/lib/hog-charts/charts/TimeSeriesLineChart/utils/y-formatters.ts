import { compactNumber, humanFriendlyCurrency, humanFriendlyDuration, humanFriendlyNumber, percentage } from 'lib/utils'
import { formatCurrency } from 'lib/utils/geography/currency'

/** Format kinds the y-axis tick formatter understands. Mirrors the set Trends already
 *  produces — no new variants until a consumer needs one. */
export type YAxisFormat =
    | 'numeric'
    | 'percentage'
    | 'percentage_scaled'
    | 'currency'
    | 'duration'
    | 'duration_ms'
    | 'short'

export interface YFormatterConfig {
    format?: YAxisFormat
    prefix?: string
    suffix?: string
    /** Maximum decimal places — passed to numeric / percentage formatters. */
    decimalPlaces?: number
    /** Minimum decimal places — passed to numeric formatter. */
    minDecimalPlaces?: number
    /** Currency code (e.g. `'USD'`). Used when `format === 'currency'`. */
    currency?: string
}

const formatCurrencyAny = formatCurrency as (amount: number, currency: string) => string

export function buildYTickFormatter(config: YFormatterConfig): (value: number) => string {
    const { format, prefix, suffix, decimalPlaces, minDecimalPlaces, currency } = config
    return (rawValue: number): string => {
        const value = Number(rawValue)
        let formatted = humanFriendlyNumber(value, decimalPlaces, minDecimalPlaces)
        switch (format) {
            case 'duration':
                formatted = humanFriendlyDuration(value)
                break
            case 'duration_ms':
                formatted = humanFriendlyDuration(value / 1000, { secondsFixed: 1 })
                break
            case 'percentage':
                formatted = percentage(value / 100, decimalPlaces)
                break
            case 'percentage_scaled':
                formatted = percentage(value, decimalPlaces)
                break
            case 'currency':
                try {
                    formatted = currency ? formatCurrencyAny(value, currency) : humanFriendlyCurrency(value)
                } catch {
                    formatted = humanFriendlyCurrency(value)
                }
                break
            case 'short':
                formatted = compactNumber(value)
                break
            case 'numeric':
            case undefined:
            default:
                break
        }
        return `${prefix ?? ''}${formatted}${suffix ?? ''}`
    }
}
