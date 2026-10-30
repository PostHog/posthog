import React from 'react'

import type { TooltipContext } from '../../core/types'
import { TooltipSurface, TooltipSwatch } from '../../overlays/TooltipSurface'
import type { GaugeThreshold } from './gauge-layout'

export interface GaugeTooltipThreshold {
    /** Index into the thresholds sorted by value. */
    index: number
    /** The threshold step with its color resolved to a concrete value. */
    threshold: GaugeThreshold
    /** The band's unclipped range: `from` is undefined for the lowest band, `to` for the highest. */
    from: number | undefined
    to: number | undefined
}

/** {@link TooltipContext} with the gauge's reading. `label` is the gauge `label`, or `''` without one. */
export interface GaugeTooltipContext extends TooltipContext {
    value: number | null
    min: number
    max: number
    /** The band the value falls in, or null without thresholds or a value. */
    threshold: GaugeTooltipThreshold | null
    /** Number of thresholds, so a tooltip can skip the band row when one color covers the range. */
    thresholdCount: number
    target: { value: number; label?: string } | null
    /** The resolved color of the value arc. */
    color: string
    /** The gauge's value formatter, for formatting any of the numbers above. */
    formatValue: (value: number) => string
}

export const GAUGE_EMPTY_VALUE = '–'

export function formatGaugeBand(threshold: GaugeTooltipThreshold, formatValue: (value: number) => string): string {
    const { from, to } = threshold
    if (from === undefined && to === undefined) {
        return 'All values'
    }
    if (from === undefined) {
        return `Below ${formatValue(to as number)}`
    }
    if (to === undefined) {
        return `${formatValue(from)} and above`
    }
    return `${formatValue(from)} – ${formatValue(to)}`
}

function Row({ name, children }: { name: string; children: React.ReactNode }): React.ReactElement {
    return (
        <>
            <span className="opacity-70">{name}</span>
            <span className="flex items-center gap-1.5 justify-self-end font-medium tabular-nums">{children}</span>
        </>
    )
}

export interface GaugeTooltipProps {
    ctx: GaugeTooltipContext
}

export function GaugeTooltip({ ctx }: GaugeTooltipProps): React.ReactElement {
    const { formatValue, threshold, target } = ctx
    return (
        <TooltipSurface data-attr="hog-chart-gauge-tooltip">
            {ctx.label ? <div className="mb-1 font-semibold">{ctx.label}</div> : null}
            <div className="grid grid-cols-[auto_auto] gap-x-4 gap-y-0.5">
                <Row name="Value">{ctx.value === null ? GAUGE_EMPTY_VALUE : formatValue(ctx.value)}</Row>
                <Row name="Range">
                    {formatValue(ctx.min)} – {formatValue(ctx.max)}
                </Row>
                {threshold && (ctx.thresholdCount > 1 || threshold.threshold.label) ? (
                    <Row name="Threshold">
                        <TooltipSwatch color={threshold.threshold.color} />
                        <span>
                            {threshold.threshold.label
                                ? `${threshold.threshold.label} · ${formatGaugeBand(threshold, formatValue)}`
                                : formatGaugeBand(threshold, formatValue)}
                        </span>
                    </Row>
                ) : null}
                {target ? <Row name={target.label ?? 'Target'}>{formatValue(target.value)}</Row> : null}
            </div>
        </TooltipSurface>
    )
}
