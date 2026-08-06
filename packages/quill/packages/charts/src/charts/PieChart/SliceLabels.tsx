import React from 'react'

import { type LabelBox, nonCollidingKeys } from '../../core/label-collision'
import { useRadialLayout } from '../../core/radial-context'
import { FONT_FAMILY, measureLabelWidth } from '../../utils/text-measure'

export { nonCollidingKeys } from '../../core/label-collision'
export type { LabelBox } from '../../core/label-collision'

export interface SliceLabelsProps {
    valueFormatter?: (value: number) => string
    /** Show the slice's value above the slice. Default true. */
    showValueOnSlice?: boolean
    /** Show the breakdown label above the slice. Default false. When both are true, the
     *  label sits above the value. */
    showLabelOnSlice?: boolean
    /** Hide labels for slices with `fraction < threshold`. Default 0.05. */
    minSlicePercentForLabel?: number
    /** Where labels sit along the radius: 0 = center, 1 = outer edge. Default 0.5 (mid-slice). */
    labelRadiusRatio?: number
    isPercent?: boolean
}

const LABEL_FONT_SIZE = 14
const LABEL_LINE_HEIGHT = 1.2
const LABEL_FONT = `600 ${LABEL_FONT_SIZE}px ${FONT_FAMILY}`
// Breathing room added around each label box so near-touching labels still count as colliding.
const LABEL_PADDING_X = 4
const LABEL_PADDING_Y = 2

const LABEL_STYLE_BASE: React.CSSProperties = {
    position: 'absolute',
    pointerEvents: 'none',
    color: 'white',
    fontSize: LABEL_FONT_SIZE,
    fontWeight: 600,
    lineHeight: LABEL_LINE_HEIGHT,
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
    labelRadiusRatio = 0.5,
    isPercent = false,
}: SliceLabelsProps): React.ReactElement | null {
    const { layout } = useRadialLayout()
    if (!showValueOnSlice && !showLabelOnSlice) {
        return null
    }
    const ratio = Math.min(1, Math.max(0, labelRadiusRatio))
    const midR = layout.innerRadius + (layout.outerRadius - layout.innerRadius) * ratio

    const boxes: LabelBox[] = []
    for (let i = 0; i < layout.slices.length; i++) {
        const slice = layout.slices[i]
        if (slice.series.visibility?.valueLabel === false || slice.fraction < minSlicePercentForLabel) {
            continue
        }
        const lines: string[] = []
        if (showLabelOnSlice) {
            lines.push(slice.series.label)
        }
        if (showValueOnSlice) {
            lines.push(isPercent ? formatPercent(slice.fraction) : valueFormatter(slice.value))
        }
        const width = Math.max(0, ...lines.map((line) => measureLabelWidth(line, LABEL_FONT)))
        boxes.push({
            // Slice positions can shift when the input series changes, but the series key is stable
            // across re-renders of the same series, which keeps React's reconciliation predictable.
            key: slice.series.key || String(i),
            x: layout.cx + Math.sin(slice.centroidAngle) * midR,
            y: layout.cy - Math.cos(slice.centroidAngle) * midR,
            halfWidth: width / 2 + LABEL_PADDING_X,
            halfHeight: (lines.length * LABEL_FONT_SIZE * LABEL_LINE_HEIGHT) / 2 + LABEL_PADDING_Y,
            value: slice.value,
            lines,
        })
    }

    const visibleKeys = nonCollidingKeys(boxes)

    return (
        <>
            {boxes
                .filter((box) => visibleKeys.has(box.key))
                .map((box) => (
                    <div
                        key={box.key}
                        data-attr="hog-chart-pie-slice-label"
                        style={{ ...LABEL_STYLE_BASE, left: Math.round(box.x), top: Math.round(box.y) }}
                    >
                        {box.lines.map((line, li) => (
                            <div key={li}>{line}</div>
                        ))}
                    </div>
                ))}
        </>
    )
}
