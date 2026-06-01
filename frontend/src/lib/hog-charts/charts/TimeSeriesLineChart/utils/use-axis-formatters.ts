import { useMemo } from 'react'

import { createXAxisTickCallback, type TimeInterval } from './dates'
import { buildYTickFormatter, type YFormatterConfig } from './y-formatters'

export interface XAxisConfig {
    /** Custom tick label formatter. When set, it wins over the date-axis auto formatter. */
    tickFormatter?: (value: string, index: number) => string | null
    hide?: boolean
    timezone?: string
    interval?: TimeInterval
    /** Raw date strings underlying each label, used to compute boundary-aware ticks.
     * If omitted, falls back to `labels`. */
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
    }, [xAxis?.tickFormatter, xAxis?.timezone, xAxis?.interval, xAxis?.allDays, labels])
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
