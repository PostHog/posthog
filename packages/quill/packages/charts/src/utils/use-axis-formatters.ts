import { useMemo } from 'react'

import { createXAxisTickCallback, type TimeInterval } from './dates'
import { buildYTickFormatter, type YFormatterConfig } from './y-formatters'

export interface XAxisConfig {
    label?: string
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
    /** Axis id — matches `Series.yAxisId`. Only meaningful in the array (multi-axis) form; the
     *  first entry defaults to the primary axis id (`'left'`). */
    id?: string
    /** Which side this axis renders on. Only meaningful in the array (multi-axis) form; the first
     *  entry defaults to `'left'`, subsequent entries to `'right'`. */
    position?: 'left' | 'right'
    label?: string
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

/** Non-hook resolution of a {@link YAxisConfig} into a tick formatter. An explicit `tickFormatter`
 *  wins; otherwise a formatter is built from the format fields, or `undefined` when none are set
 *  (so callers auto-format against the axis's own ticks). Shared by {@link useYTickFormatter} and
 *  the per-axis resolution in multi-axis charts (where a hook can't run per array entry). */
export function resolveYTickFormatter(yAxis: YAxisConfig | undefined): ((value: number) => string) | undefined {
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
}

export function useYTickFormatter(yAxis: YAxisConfig | undefined): ((value: number) => string) | undefined {
    // Read the formatter-relevant fields here (not the whole object) so the memo stays stable across
    // unrelated config-identity changes — the same field set forms the dependency array.
    const { tickFormatter, format, prefix, suffix, decimalPlaces, minDecimalPlaces, currency } = yAxis ?? {}
    return useMemo(
        () => resolveYTickFormatter({ tickFormatter, format, prefix, suffix, decimalPlaces, minDecimalPlaces, currency }),
        [tickFormatter, format, prefix, suffix, decimalPlaces, minDecimalPlaces, currency]
    )
}
