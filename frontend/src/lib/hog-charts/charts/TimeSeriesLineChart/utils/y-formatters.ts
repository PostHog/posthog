import { compactNumber, humanFriendlyCurrency, humanFriendlyDuration, humanFriendlyNumber, percentage } from 'lib/utils'
import { formatCurrency } from 'lib/utils/geography/currency'

export type YAxisFormat =
    | 'numeric'
    | 'percentage'
    | 'percentage_scaled'
    | 'currency'
    | 'duration'
    | 'duration_ms'
    | 'short'

export interface YFormatterConfig {
    /** `percentage` expects values in `0–100`; `percentage_scaled` expects values in `0–1`. */
    format?: YAxisFormat
    prefix?: string
    suffix?: string
    decimalPlaces?: number
    minDecimalPlaces?: number
    /** Currency code (e.g. `'USD'`). Used when `format === 'currency'`. */
    currency?: string
}

// `formatCurrency` requires a `CurrencyCode` enum imported from `~/queries/schema/...`,
// which `lib/hog-charts` cannot pull in. The runtime call uses `getCurrencySymbol`
// which already validates the string, so the cast is safe — invalid codes throw and
// fall through to the `humanFriendlyCurrency` branch below.
const formatCurrencyAny = formatCurrency as (amount: number, currency: string) => string

export function buildYTickFormatter(config: YFormatterConfig): (value: number) => string {
    const { format, prefix, suffix, decimalPlaces, minDecimalPlaces, currency } = config
    return (value: number): string => {
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
