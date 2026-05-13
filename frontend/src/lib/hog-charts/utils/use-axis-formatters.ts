import { useMemo } from 'react'

import { createXAxisTickCallback, type TimeInterval } from './dates'
import { buildYTickFormatter, type YFormatterConfig } from './y-formatters'

export interface XAxisConfig {
    /** Explicit tick formatter. When set, it wins over the auto date formatter. */
    tickFormatter?: (value: string, index: number) => string | null
    hide?: boolean
    /** Timezone used when interpreting date labels for the auto date formatter. */
    timezone?: string
    /** Bucket size for the auto date formatter. */
    interval?: TimeInterval
    /** Source dates for the auto date formatter. Falls back to `labels` when omitted. */
    allDays?: string[]
}

export interface YAxisConfig extends YFormatterConfig {
    scale?: 'linear' | 'log'
    /** Custom tick formatter. When set, it wins over `format`. */
    tickFormatter?: (value: number) => string
    hide?: boolean
    showGrid?: boolean
}

export function useXTickFormatter(
    xAxis: XAxisConfig | undefined,
    labels: string[]
): ((value: string, index: number) => string | null) | undefined {
    // Resolve outside the memo so `labels` only participates as a dep when it's
    // actually the source — when `xAxis.allDays` is provided, label-only changes
    // shouldn't rebuild the formatter (and ripple a new identity through context).
    const effectiveAllDays = xAxis?.allDays ?? labels
    return useMemo(() => {
        if (xAxis?.tickFormatter) {
            return xAxis.tickFormatter
        }
        if (xAxis?.timezone && xAxis?.interval) {
            return createXAxisTickCallback({
                timezone: xAxis.timezone,
                interval: xAxis.interval,
                allDays: effectiveAllDays,
            })
        }
        return undefined
    }, [xAxis?.tickFormatter, xAxis?.timezone, xAxis?.interval, effectiveAllDays])
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
    }, [
        yAxis?.tickFormatter,
        yAxis?.format,
        yAxis?.prefix,
        yAxis?.suffix,
        yAxis?.decimalPlaces,
        yAxis?.minDecimalPlaces,
        yAxis?.currency,
    ])
}
