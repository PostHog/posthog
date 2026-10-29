import React, { useMemo } from 'react'

import { useChartLayout } from '../../core/chart-context'
import { type LabelBox, nonCollidingKeys } from '../../core/label-collision'
import type { ResolvedSeries } from '../../core/types'
import { measureLabelWidth } from '../../utils/text-measure'
import { slopeDelta, slopeEnd } from './slope-data'
import { SLOPE_LABEL_FONT, SLOPE_LABEL_FONT_SIZE, SlopeLabel } from './SlopeLabel'

const LABEL_PADDING_X = 4
const LABEL_PADDING_Y = 3

export interface SlopeSeriesLabelsProps {
    /** Render the series name labels. Default true. */
    show?: boolean
    /** Px to the right of the last point where the name labels begin. */
    offsetX?: number
}

interface NameEntry {
    box: LabelBox
    color: string
    label: string
}

/** Series name labels anchored beside each series' last point. When two names would overlap, the
 *  series with the larger change (`|end − start|`) wins — it is always kept, and lower-change names
 *  that collide with it are dropped (requirement: the steepest line never loses its label). */
export function SlopeSeriesLabels({ show = true, offsetX = 8 }: SlopeSeriesLabelsProps): React.ReactElement | null {
    const { series, scales, labels } = useChartLayout()

    const entries = useMemo<NameEntry[]>(() => {
        if (!show || labels.length < 2) {
            return []
        }
        const x1 = scales.x(labels[labels.length - 1])
        if (x1 == null) {
            return []
        }
        const out: NameEntry[] = []
        for (const s of series as ResolvedSeries[]) {
            if (s.visibility?.excluded || s.visibility?.valueLabel === false) {
                continue
            }
            const y = scales.y(slopeEnd(s))
            if (!isFinite(y)) {
                continue
            }
            const width = measureLabelWidth(s.label, SLOPE_LABEL_FONT)
            out.push({
                color: s.color,
                label: s.label,
                box: {
                    key: s.key,
                    x: x1 + offsetX + width / 2,
                    y,
                    halfWidth: width / 2 + LABEL_PADDING_X,
                    halfHeight: SLOPE_LABEL_FONT_SIZE / 2 + LABEL_PADDING_Y,
                    value: Math.abs(slopeDelta(s)),
                    lines: [s.label],
                },
            })
        }
        return out
    }, [series, scales, labels, show, offsetX])

    const visibleKeys = useMemo(() => nonCollidingKeys(entries.map((e) => e.box)), [entries])

    if (entries.length === 0) {
        return null
    }

    return (
        <>
            {entries
                .filter((e) => visibleKeys.has(e.box.key))
                .map((e) => (
                    <SlopeLabel
                        key={e.box.key}
                        x={e.box.x}
                        y={e.box.y}
                        transform="translate(-50%, -50%)"
                        color={e.color}
                        text={e.label}
                        dataAttr="hog-chart-slope-series-label"
                    />
                ))}
        </>
    )
}
