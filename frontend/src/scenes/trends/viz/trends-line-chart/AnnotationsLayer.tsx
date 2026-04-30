import React, { useMemo } from 'react'

import { Chart } from 'lib/Chart'
import { AnnotationsOverlay } from 'lib/components/AnnotationsOverlay'
import { computeVisibleXLabels, useChartLayout } from 'lib/hog-charts'

interface AnnotationsLayerProps {
    /** Numeric insight id used by the annotations logic. Pass `'new'` for unsaved insights. */
    insightNumericId: number | 'new'
    /** Per-data-point date strings; used for grouping annotations. */
    dates: string[]
    /** Custom x-axis tick formatter — must match the one passed to the chart so the
     *  computed tick set lines up with what the user sees. */
    xTickFormatter?: (value: string, index: number) => string | null
}

const WRAPPER_STYLE: React.CSSProperties = {
    // Re-enable pointer-events here because Chart's overlay layer disables them
    // for non-interactive overlays (axis labels, crosshair, reference lines).
    pointerEvents: 'auto',
}

// Annotation badges must not drive the chart's crosshair or onPointClick.
const stopPointerPropagation = (e: React.MouseEvent<HTMLDivElement>): void => {
    e.stopPropagation()
}

export function AnnotationsLayer({
    insightNumericId,
    dates,
    xTickFormatter,
}: AnnotationsLayerProps): React.ReactElement | null {
    const { scales, dimensions, labels } = useChartLayout()

    const chartLike = useMemo(() => {
        const visibleXLabels = computeVisibleXLabels(labels, scales.x, xTickFormatter)
        const points = labels.map((label) => ({ x: scales.x(label) ?? 0, y: 0 }))
        const ticks = visibleXLabels.map((v) => ({ value: v.index }))
        return {
            scales: {
                x: {
                    ticks,
                    left: dimensions.plotLeft,
                    top: dimensions.plotTop + dimensions.plotHeight,
                },
            },
            _metasets: [{ data: points }],
        }
    }, [labels, scales.x, dimensions.plotLeft, dimensions.plotTop, dimensions.plotHeight, xTickFormatter])

    if (chartLike.scales.x.ticks.length < 2) {
        return null
    }

    return (
        <div
            className="HogChartsAnnotationsLayer"
            style={WRAPPER_STYLE}
            onClick={stopPointerPropagation}
            onMouseMove={stopPointerPropagation}
            onMouseDown={stopPointerPropagation}
        >
            <AnnotationsOverlay
                chart={chartLike as unknown as Chart}
                dates={dates}
                chartWidth={dimensions.width}
                chartHeight={dimensions.height}
                insightNumericId={insightNumericId}
            />
        </div>
    )
}
