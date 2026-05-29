import React from 'react'

import { useRadialLayout } from '../../core/radial-context'

export interface SliceLabelsProps {
    valueFormatter?: (value: number) => string
    /** Show the slice's value above the slice. Default true. */
    showValueOnSlice?: boolean
    /** Show the breakdown label above the slice. Default false. When both are true, the
     *  label sits above the value. */
    showLabelOnSlice?: boolean
    /** Hide labels for slices with `fraction < threshold`. Default 0.05. */
    minSlicePercentForLabel?: number
    isPercent?: boolean
}

const LABEL_STYLE_BASE: React.CSSProperties = {
    position: 'absolute',
    pointerEvents: 'none',
    color: 'white',
    fontSize: 12,
    fontWeight: 600,
    lineHeight: 1.2,
    textAlign: 'center',
    textShadow: '0 1px 2px rgba(0, 0, 0, 0.45)',
    whiteSpace: 'nowrap',
    transform: 'translate(-50%, -50%)',
}

function defaultFormatter(v: number): string {
    return v.toLocaleString()
}

function formatPercent(fraction: number): string {
    return `${Math.round(fraction * 1000) / 10}%`
}

export function SliceLabels({
    valueFormatter = defaultFormatter,
    showValueOnSlice = true,
    showLabelOnSlice = false,
    minSlicePercentForLabel = 0.05,
    isPercent = false,
}: SliceLabelsProps): React.ReactElement | null {
    const { layout } = useRadialLayout()
    if (!showValueOnSlice && !showLabelOnSlice) {
        return null
    }
    const midR = layout.innerRadius + (layout.outerRadius - layout.innerRadius) / 2
    return (
        <>
            {layout.slices.map((slice, i) => {
                if (slice.series.visibility?.valueLabel === false) {
                    return null
                }
                if (slice.fraction < minSlicePercentForLabel) {
                    return null
                }
                const x = layout.cx + Math.sin(slice.centroidAngle) * midR
                const y = layout.cy - Math.cos(slice.centroidAngle) * midR
                const valueText = isPercent ? formatPercent(slice.fraction) : valueFormatter(slice.value)
                return (
                    <div
                        // Slice positions can shift when the input series changes, but `seriesIndex`
                        // is stable across re-renders of the same series, which keeps React's
                        // reconciliation predictable.
                        key={slice.series.key || i}
                        data-attr="hog-chart-pie-slice-label"
                        style={{ ...LABEL_STYLE_BASE, left: Math.round(x), top: Math.round(y) }}
                    >
                        {showLabelOnSlice ? <div>{slice.series.label}</div> : null}
                        {showValueOnSlice ? <div>{valueText}</div> : null}
                    </div>
                )
            })}
        </>
    )
}
