import { useMemo } from 'react'

import { DEFAULT_Y_AXIS_ID, type TooltipConfig, type YAxis } from '../core/types'
import { createTooltipDateFormatter, createXAxisTickCallback, type TimeInterval } from './dates'
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
    /** Y-axis baseline behavior. The default (`undefined`/`true`) clamps a non-negative axis down to
     *  0. Set `false` to float the axis to its data range instead (zoom in on the variation). Ignored
     *  on a log scale; honored per axis in the array (multi-axis) form, except axes carrying bar
     *  series, which always draw from 0. */
    startAtZero?: boolean
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

/** Tooltip config with the header label defaulted to a full formatted date when the x-axis is
 *  date-driven (`timezone` + `interval` set) — the axis ticks are already auto-formatted then, so
 *  a raw ISO header would be the odd one out. An explicit `labelFormatter` wins. */
export function useTimeSeriesTooltipConfig(
    tooltip: TooltipConfig | undefined,
    xAxis: XAxisConfig | undefined
): TooltipConfig | undefined {
    const { timezone, interval } = xAxis ?? {}
    return useMemo(() => {
        if (tooltip?.labelFormatter || !timezone || !interval) {
            return tooltip
        }
        return { ...tooltip, labelFormatter: createTooltipDateFormatter({ interval, timezone }) }
    }, [tooltip, timezone, interval])
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

interface NormalizedYAxis {
    id: string
    position: 'left' | 'right'
    config: YAxisConfig
}

/** Normalize the user `yAxis` config into a per-axis list. A single object (or omitted) is the
 *  primary left axis; an array assigns ids/positions, defaulting the first entry to the primary
 *  left axis and subsequent entries to the right. */
export function normalizeYAxisList(yAxis: YAxisConfig | YAxisConfig[] | undefined): NormalizedYAxis[] {
    if (!Array.isArray(yAxis)) {
        return yAxis ? [{ id: DEFAULT_Y_AXIS_ID, position: 'left', config: yAxis }] : []
    }
    return yAxis.map((config, index) => ({
        id: config.id ?? (index === 0 ? DEFAULT_Y_AXIS_ID : `axis-${index}`),
        position: config.position ?? (index === 0 ? 'left' : 'right'),
        config,
    }))
}

/** Resolve a normalized axis list into the {@link YAxis}es the base chart consumes —
 *  each axis's id, side, scale, label, and resolved tick formatter. */
export function buildYAxes(axisList: NormalizedYAxis[]): YAxis[] {
    return axisList.map(({ id, position, config }) => ({
        id,
        position,
        scaleType: config.scale,
        tickFormatter: resolveYTickFormatter(config),
        label: config.label,
        hide: config.hide,
        startAtZero: config.startAtZero,
    }))
}

/** Resolve the primary (left) axis from a normalized list — the entry whose id is the default
 *  axis id, falling back to the first entry. Drives the base chart's scalar y-config. */
export function primaryYAxisConfig(axisList: NormalizedYAxis[]): YAxisConfig | undefined {
    return (axisList.find((a) => a.id === DEFAULT_Y_AXIS_ID) ?? axisList[0])?.config
}

export function useYTickFormatter(yAxis: YAxisConfig | undefined): ((value: number) => string) | undefined {
    // Read the formatter-relevant fields here (not the whole object) so the memo stays stable across
    // unrelated config-identity changes — the same field set forms the dependency array.
    const { tickFormatter, format, prefix, suffix, decimalPlaces, minDecimalPlaces, currency } = yAxis ?? {}
    return useMemo(
        () =>
            resolveYTickFormatter({ tickFormatter, format, prefix, suffix, decimalPlaces, minDecimalPlaces, currency }),
        [tickFormatter, format, prefix, suffix, decimalPlaces, minDecimalPlaces, currency]
    )
}
