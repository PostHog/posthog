import { scaleLinear } from 'd3'
import { useActions, useValues, type BuiltLogic } from 'kea'
import { useEffect, useId, useMemo } from 'react'

import { useChartHover, useChartLayout } from '@posthog/quill-charts'

import type { offlineExperimentsLogicType } from './offlineExperimentsLogic'

export function OfflineScoreTrendCrosshair({
    logic,
    xDomain,
}: {
    logic: BuiltLogic<offlineExperimentsLogicType>
    xDomain: [number, number]
}): JSX.Element | null {
    const chartId = useId()
    const { hoveredTrend } = useValues(logic)
    const { setHoveredTrend, clearHoveredTrend } = useActions(logic)
    const { hoverIndex } = useChartHover()
    const { labels, scales, dimensions, theme } = useChartLayout()
    const { plotLeft, plotWidth, plotTop, plotHeight } = dimensions
    const timeScale = useMemo(
        () =>
            scaleLinear()
                .domain(xDomain)
                .range([plotLeft, plotLeft + plotWidth]),
        [xDomain, plotLeft, plotWidth]
    )
    const hoverX = hoverIndex < 0 ? undefined : scales.x(labels[hoverIndex])
    const timestamp = hoverX !== undefined && Number.isFinite(hoverX) ? Math.round(timeScale.invert(hoverX)) : null

    useEffect(() => {
        if (timestamp !== null) {
            setHoveredTrend(chartId, timestamp)
        } else {
            clearHoveredTrend(chartId)
        }
    }, [chartId, timestamp, setHoveredTrend, clearHoveredTrend])

    useEffect(() => () => clearHoveredTrend(chartId), [chartId, clearHoveredTrend])

    if (!hoveredTrend || hoveredTrend.timestamp < xDomain[0] || hoveredTrend.timestamp > xDomain[1]) {
        return null
    }

    const x = timeScale(hoveredTrend.timestamp)
    return (
        <svg className="absolute inset-0 w-full h-full pointer-events-none" aria-hidden>
            <line
                data-attr="offline-score-crosshair"
                x1={x}
                x2={x}
                y1={plotTop}
                y2={plotTop + plotHeight}
                stroke={theme.crosshairColor ?? theme.gridColor}
                strokeDasharray={(theme.crosshairDashPattern ?? [3, 3]).join(' ')}
            />
        </svg>
    )
}
