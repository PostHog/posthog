import { createContext, useContext, useMemo } from 'react'

import type { PointClickData, Series } from '@posthog/quill-charts'

import { highlightChartSeries } from '~/queries/nodes/DataVisualization/Components/Charts/sqlChartHighlighting'

export interface ResultChartPoint {
    seriesKey: string
    label: string
}

export const ResultChartSelectionContext = createContext<{
    point?: ResultChartPoint
    capturePoint: (point: PointClickData) => void
    captureCell: (point: ResultChartPoint) => void
}>({ capturePoint: () => {}, captureCell: () => {} })

export function useResultChartPoint(): (point: PointClickData) => void {
    return useContext(ResultChartSelectionContext).capturePoint
}

export function useResultBarSelection<Meta>(
    series: Series<Meta>[],
    labels: string[],
    colors: string[]
): Series<Meta>[] {
    const { point } = useContext(ResultChartSelectionContext)
    return useMemo(
        () =>
            point && labels.includes(point.label) && series.some((entry) => entry.key === point.seriesKey)
                ? highlightChartSeries(
                      series,
                      colors,
                      (key, index) => key === point.seriesKey && labels[index] === point.label
                  )
                : series,
        [series, labels, colors, point]
    )
}
