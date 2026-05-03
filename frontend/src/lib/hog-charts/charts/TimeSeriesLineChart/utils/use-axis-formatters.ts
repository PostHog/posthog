import { useMemo } from 'react'

import { createXAxisTickCallback, type TimeInterval } from './dates'
import { buildYTickFormatter, type YAxisFormat } from './y-formatters'

export interface XAxisConfig {
    /** Custom tick label formatter. When set, it wins over the date-axis auto formatter. */
    tickFormatter?: (value: string, index: number) => string | null
    hide?: boolean
    /** IANA timezone (e.g. `UTC`, `America/New_York`) for date-axis tick formatting.
     * Combined with `interval`, enables auto-formatting via `createXAxisTickCallback`. */
    timezone?: string
    /** Bucket size of the X axis. Combined with `timezone`, enables auto-formatting. */
    interval?: TimeInterval
    /** The raw date strings underlying each label, used to compute boundary-aware ticks.
     * If omitted, falls back to `labels`. */
    allDays?: string[]
}

export interface YAxisConfig {
    /** `linear` (default) or `log`. Log falls back to a linear scale when no positive values exist. */
    scale?: 'linear' | 'log'
    /** Custom tick formatter. When set, it wins over `format`. */
    tickFormatter?: (value: number) => string
    hide?: boolean
    showGrid?: boolean
    /** Built-in tick format. Used when `tickFormatter` is not set. */
    format?: YAxisFormat
    prefix?: string
    suffix?: string
    decimalPlaces?: number
    minDecimalPlaces?: number
    /** Currency code (e.g. `'USD'`). Used when `format === 'currency'`. */
    currency?: string
}

export function useXTickFormatter(
    xAxis: XAxisConfig | undefined,
    labels: string[]
): ((value: string, index: number) => string | null) | undefined {
    return useMemo(() => {
        if (xAxis?.tickFormatter) {
            return xAxis.tickFormatter
        }
        if (!xAxis?.timezone || !xAxis?.interval) {
            return undefined
        }
        return createXAxisTickCallback({
            timezone: xAxis.timezone,
            interval: xAxis.interval,
            allDays: xAxis.allDays ?? labels,
        })
    }, [xAxis, labels])
}

export function useYTickFormatter(yAxis: YAxisConfig | undefined): ((value: number) => string) | undefined {
    return useMemo(() => {
        if (yAxis?.tickFormatter) {
            return yAxis.tickFormatter
        }
        if (
            yAxis?.format === undefined &&
            yAxis?.prefix === undefined &&
            yAxis?.suffix === undefined &&
            yAxis?.decimalPlaces === undefined &&
            yAxis?.minDecimalPlaces === undefined &&
            yAxis?.currency === undefined
        ) {
            return undefined
        }
        return buildYTickFormatter({
            format: yAxis.format,
            prefix: yAxis.prefix,
            suffix: yAxis.suffix,
            decimalPlaces: yAxis.decimalPlaces,
            minDecimalPlaces: yAxis.minDecimalPlaces,
            currency: yAxis.currency,
        })
    }, [yAxis])
}
