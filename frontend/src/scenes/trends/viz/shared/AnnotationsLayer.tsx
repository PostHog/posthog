import React, { useCallback, useMemo } from 'react'

import { Chart } from 'lib/Chart'
import { AnnotationsOverlay } from 'lib/components/AnnotationsOverlay'
import { computeVisibleXLabels, useChartLayout } from 'lib/hog-charts'

interface AnnotationsLayerProps {
    /** Numeric insight id used by the annotations logic. Pass `'new'` for unsaved insights. */
    insightNumericId: number | 'new'
    /** Per-data-point date strings; used for grouping annotations. */
    dates: string[]
    /** Series key whose bar should anchor annotations in compare-against-previous grouped
     *  bar layouts. Without it, annotations land on the band center (between current
     *  and previous bars) instead of the current-period bar. */
    seriesKey?: string
    /** Per-data-point date strings for the previous period in compare-against-previous
     *  layouts. When provided alongside `previousSeriesKey`, previous-period annotations
     *  share the overlay so cluster merging and tick suppression apply across periods. */
    previousDates?: string[]
    /** Series key for the previous-period bar. Required for previous-period annotations
     *  to anchor on the correct bar within each band. */
    previousSeriesKey?: string
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
    seriesKey,
    previousDates,
    previousSeriesKey,
}: AnnotationsLayerProps): React.ReactElement | null {
    const { scales, dimensions, labels, axis } = useChartLayout()
    const xTickFormatter = axis.xTickFormatter

    const chartLike = useMemo(() => {
        const visibleXLabels = computeVisibleXLabels(labels, scales.x, xTickFormatter)
        const points = labels.map((label) => ({ x: scales.x(label, seriesKey) ?? 0, y: 0 }))
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
        // eslint-disable-next-line react-hooks/exhaustive-deps -- only `scales.x` is read; `scales` itself is unused.
    }, [labels, scales.x, seriesKey, dimensions.plotLeft, dimensions.plotTop, dimensions.plotHeight, xTickFormatter])

    const hasPreviousTrack = !!(previousDates && previousSeriesKey)

    const getPreviousDataPointX = useCallback(
        (dataIndex: number): number | null => {
            if (!hasPreviousTrack) {
                return null
            }
            const label = labels[dataIndex]
            if (label === undefined) {
                return null
            }
            return scales.x(label, previousSeriesKey) ?? null
        },
        // eslint-disable-next-line react-hooks/exhaustive-deps -- only `scales.x` is read; `scales` itself is unused.
        [labels, scales.x, previousSeriesKey, hasPreviousTrack]
    )

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
                previousDates={hasPreviousTrack ? previousDates : undefined}
                getPreviousDataPointX={hasPreviousTrack ? getPreviousDataPointX : undefined}
            />
        </div>
    )
}
