import {
    type TooltipContext,
    TooltipFooter,
    TooltipSurface,
    TooltipSwatch,
    funnelConversionRate,
} from '@posthog/quill-charts'

import { humanFriendlyNumber, percentage } from 'lib/utils/numbers'

import type { VariantFunnelMeta } from './types'

function TooltipRow({ label, value }: { label: string; value: React.ReactNode }): JSX.Element {
    return (
        <div className="flex items-center justify-between gap-4">
            <span className="opacity-60">{label}</span>
            <strong className="tabular-nums">{value}</strong>
        </div>
    )
}

/** Tooltip for the hovered variant's bar: its counts at this step and how it converted into it. */
export function FunnelTooltip({
    ctx,
    steps,
    showClickHint,
}: {
    ctx: TooltipContext<VariantFunnelMeta>
    steps: string[]
    showClickHint: boolean
}): JSX.Element | null {
    const entry = ctx.seriesData.find((e) => e.series.key === ctx.hoveredSeriesKey) ?? ctx.seriesData[0]
    const meta = entry?.series.meta
    if (!entry || !meta) {
        return null
    }
    const stepIndex = ctx.dataIndex
    const count = meta.counts[stepIndex] ?? 0
    const previousCount = stepIndex > 0 ? (meta.counts[stepIndex - 1] ?? 0) : null
    return (
        <TooltipSurface>
            <div className="flex items-center gap-2 font-semibold mb-1">
                <TooltipSwatch color={entry.color} />
                <span className="truncate">
                    {steps[stepIndex]} · {meta.variantKey}
                </span>
            </div>
            <TooltipRow label={stepIndex === 0 ? 'Entered' : 'Converted'} value={humanFriendlyNumber(count)} />
            {previousCount != null && (
                <>
                    <TooltipRow label="Dropped off" value={humanFriendlyNumber(Math.max(previousCount - count, 0))} />
                    <TooltipRow
                        label="Conversion so far"
                        value={percentage(funnelConversionRate(count, meta.counts[0] ?? 0), 2, true)}
                    />
                    <TooltipRow
                        label="Conversion from previous"
                        value={percentage(funnelConversionRate(count, previousCount), 2, true)}
                    />
                </>
            )}
            {showClickHint && <TooltipFooter>Click to view users</TooltipFooter>}
        </TooltipSurface>
    )
}
