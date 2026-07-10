import { Chart, ChartEvent, ChartType, DeepPartial, InteractionItem, LegendOptions } from 'lib/Chart'
import { TooltipConfig } from 'scenes/insights/InsightTooltip/insightTooltipUtils'

import { GoalLine, TrendsFilter } from '~/queries/schema/schema-general'
import { GraphDataset, GraphPoint, GraphPointPayload, GraphType } from '~/types'

import { AnomalyPoint } from 'products/alerts/frontend/types'

export function onChartClick(
    event: ChartEvent,
    chart: Chart,
    datasets: GraphDataset[],
    onClick?: { (payload: GraphPointPayload): void | undefined }
): void {
    const nativeEvent = event.native
    if (!nativeEvent) {
        return
    }
    // Get all points along line
    const sortPoints = (a: InteractionItem, b: InteractionItem): number => {
        const eventY = event.y ?? 0
        // Compare distance to bar center, not top edge (stacked bars share edges)
        const aEl = a.element as unknown as { y: number; base?: number }
        const bEl = b.element as unknown as { y: number; base?: number }
        const aY = aEl.base != null ? (aEl.y + aEl.base) / 2 : aEl.y
        const bY = bEl.base != null ? (bEl.y + bEl.base) / 2 : bEl.y
        return Math.abs(aY - eventY) - Math.abs(bY - eventY)
    }
    const pointsIntersectingLine = chart
        .getElementsAtEventForMode(
            nativeEvent,
            'index',
            {
                intersect: false,
            },
            true
        )
        .sort(sortPoints)
    // Get all points intersecting clicked point
    const pointsIntersectingClick = chart
        .getElementsAtEventForMode(
            nativeEvent,
            'point',
            {
                intersect: true,
            },
            true
        )
        .sort(sortPoints)

    if (!pointsIntersectingClick.length && !pointsIntersectingLine.length) {
        return
    }

    const clickedPointNotLine = pointsIntersectingClick.length !== 0

    // Use the tooltip's active data point so the modal matches what the user sees,
    // but only when the tooltip refers to the same data column as the click
    const tooltipDataPoint = chart.tooltip?.dataPoints?.[0]
    const tooltipIsForThisColumn =
        tooltipDataPoint != null &&
        pointsIntersectingLine.some(
            (p) => p.datasetIndex === tooltipDataPoint.datasetIndex && p.index === tooltipDataPoint.dataIndex
        )
    const referencePoint: GraphPoint = tooltipIsForThisColumn
        ? {
              datasetIndex: tooltipDataPoint.datasetIndex,
              index: tooltipDataPoint.dataIndex,
              element: tooltipDataPoint.element,
              dataset: datasets[tooltipDataPoint.datasetIndex],
          }
        : clickedPointNotLine
          ? { ...pointsIntersectingClick[0], dataset: datasets[pointsIntersectingClick[0].datasetIndex] }
          : { ...pointsIntersectingLine[0], dataset: datasets[pointsIntersectingLine[0].datasetIndex] }

    const crossDataset = datasets
        .filter((_dt) => !_dt.dotted)
        .map((_dt) => ({
            ..._dt,
            personUrl: _dt.persons_urls?.[referencePoint.index].url,
            pointValue: _dt.data[referencePoint.index],
        }))

    onClick?.({
        points: {
            pointsIntersectingLine: pointsIntersectingLine.map((p) => ({
                ...p,
                dataset: datasets[p.datasetIndex],
            })),
            pointsIntersectingClick: pointsIntersectingClick.map((p) => ({
                ...p,
                dataset: datasets[p.datasetIndex],
            })),
            clickedPointNotLine,
            referencePoint,
        },
        index: referencePoint.index,
        crossDataset,
        seriesId: datasets[referencePoint.datasetIndex].id,
    })
}

export interface LineGraphProps {
    datasets: GraphDataset[]
    labels: string[]
    type: GraphType
    isInProgress?: boolean
    onClick?: (payload: GraphPointPayload) => void
    ['data-attr']: string
    inSharedMode?: boolean
    showPersonsModal?: boolean
    tooltip?: TooltipConfig
    inSurveyView?: boolean
    isArea?: boolean
    incompletenessOffsetFromEnd?: number // Number of data points at end of dataset to replace with a dotted line. Only used in line graphs.
    labelGroupType: number | 'people' | 'none'
    trendsFilter?: TrendsFilter | null
    formula?: string | null
    showValuesOnSeries?: boolean | null
    showPercentStackView?: boolean | null
    supportsPercentStackView?: boolean
    showPercentView?: boolean | null
    hideAnnotations?: boolean
    hideXAxis?: boolean
    hideYAxis?: boolean
    inCardView?: boolean
    legend?: DeepPartial<LegendOptions<ChartType>>
    yAxisScaleType?: string | null
    showMultipleYAxes?: boolean | null
    goalLines?: GoalLine[]
    isStacked?: boolean
    showTrendLines?: boolean
    anomalyPoints?: AnomalyPoint[]
    ignoreActionsInSeriesLabels?: boolean
    datalabelFormatter?: (value: number, datasetIndex: number) => string
    onDateRangeZoom?: (dateFrom: string, dateTo: string) => void
}
