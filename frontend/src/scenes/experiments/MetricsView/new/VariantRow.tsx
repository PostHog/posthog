import { humanFriendlyNumber } from 'lib/utils'
import { ChartCell } from './ChartCell'
import { type ExperimentVariantResult, formatPercentageChange, getNiceTickValues } from '../shared/utils'
import { IconArrowUp, IconTrendingDown } from 'lib/lemon-ui/icons'
import { ExperimentMetric, NewExperimentQueryResponse, ExperimentStatsBase } from '~/queries/schema/schema-general'
import { Experiment, InsightType } from '~/types'
import {
    CELL_HEIGHT,
    VIEW_BOX_WIDTH,
    SVG_EDGE_MARGIN,
    CHART_CELL_VIEW_BOX_HEIGHT,
    GRID_LINES_OPACITY,
} from './constants'
import { MetricHeader } from '../shared/MetricHeader'
import { DetailsButton } from './DetailsButton'
import { DetailsModal } from './DetailsModal'
import { useState } from 'react'
import { useChartColors } from '../shared/colors'
import { useAxisScale } from './useAxisScale'
import { GridLines } from './GridLines'

interface VariantRowProps {
    data: ExperimentVariantResult | ExperimentStatsBase // Variant or baseline data
    isBaseline: boolean
    isFirstRow: boolean // True for the first row (baseline), which renders rowspan cells
    isLastRow: boolean
    chartRadius: number
    metricIndex: number
    isAlternatingRow: boolean
    metric: ExperimentMetric
    metricType: InsightType
    isSecondary: boolean
    isLastMetric: boolean
    totalRows: number
    onDuplicateMetric?: () => void
    canDuplicateMetric?: boolean
    experiment: Experiment
    result: NewExperimentQueryResponse
}

export function VariantRow({
    data,
    isBaseline,
    isFirstRow,
    isLastRow,
    chartRadius,
    metricIndex,
    isAlternatingRow,
    metric,
    metricType,
    isSecondary,
    isLastMetric,
    totalRows,
    onDuplicateMetric,
    canDuplicateMetric,
    experiment,
    result,
}: VariantRowProps): JSX.Element {
    const [isModalOpen, setIsModalOpen] = useState(false)
    const colors = useChartColors()
    const scale = useAxisScale(chartRadius, VIEW_BOX_WIDTH, SVG_EDGE_MARGIN)

    // Helper function to format data
    const formatData = (): { formattedValue: string } => {
        const primaryValue = data.sum / data.number_of_samples
        const formattedValue =
            metric && 'metric_type' in metric && metric.metric_type === 'mean'
                ? primaryValue.toFixed(2)
                : `${(primaryValue * 100).toFixed(2)}%`
        return { formattedValue }
    }

    const { formattedValue } = formatData()
    const changeResult = !isBaseline ? formatPercentageChange(data as ExperimentVariantResult) : null

    return (
        <tr
            className="hover:bg-bg-hover group [&:last-child>td]:border-b-0"
            style={{ height: `${CELL_HEIGHT}px`, maxHeight: `${CELL_HEIGHT}px` }}
        >
            {/* Metric column - only render for first row with rowspan */}
            {isFirstRow && (
                <td
                    className={`w-1/5 border-r border-border-bold p-3 align-top text-left relative overflow-hidden ${
                        !isLastMetric ? 'border-b' : ''
                    } ${isAlternatingRow ? 'bg-bg-table' : 'bg-bg-light'}`}
                    rowSpan={totalRows}
                    style={{
                        height: `${CELL_HEIGHT * totalRows}px`,
                        maxHeight: `${CELL_HEIGHT * totalRows}px`,
                    }}
                >
                    <MetricHeader
                        metricIndex={metricIndex}
                        metric={metric}
                        metricType={metricType}
                        isPrimaryMetric={!isSecondary}
                        canDuplicateMetric={canDuplicateMetric || false}
                        onDuplicateMetricClick={() => onDuplicateMetric?.()}
                    />
                </td>
            )}

            {/* Variant name */}
            <td
                className={`w-20 p-3 align-top text-left whitespace-nowrap overflow-hidden ${
                    isAlternatingRow ? 'bg-bg-table' : 'bg-bg-light'
                } ${isLastRow ? 'border-b border-border-bold' : ''}`}
                style={{ height: `${CELL_HEIGHT}px`, maxHeight: `${CELL_HEIGHT}px` }}
            >
                <div className="text-sm text-text-primary whitespace-nowrap">
                    <span className="text-[#2563eb]">—</span>{' '}
                    {isBaseline ? 'Baseline' : (data as ExperimentVariantResult).key}
                </div>
            </td>

            {/* Value column */}
            <td
                className={`w-24 p-3 align-top text-left whitespace-nowrap overflow-hidden ${
                    isAlternatingRow ? 'bg-bg-table' : 'bg-bg-light'
                } ${isLastRow ? 'border-b border-border-bold' : ''}`}
                style={{ height: `${CELL_HEIGHT}px`, maxHeight: `${CELL_HEIGHT}px` }}
            >
                <div className="text-sm">
                    <div className="text-text-primary">{formattedValue}</div>
                    <div className="text-xs text-muted">
                        {data.sum} / {humanFriendlyNumber(data.number_of_samples || 0)}
                    </div>
                </div>
            </td>

            {/* Change column */}
            <td
                className={`w-20 p-3 align-top text-left whitespace-nowrap overflow-hidden ${
                    isAlternatingRow ? 'bg-bg-table' : 'bg-bg-light'
                } ${isLastRow ? 'border-b border-border-bold' : ''}`}
                style={{ height: `${CELL_HEIGHT}px`, maxHeight: `${CELL_HEIGHT}px` }}
            >
                {isBaseline ? (
                    <div className="text-xs text-muted" />
                ) : (
                    changeResult && (
                        <div className="flex items-center gap-1 text-sm">
                            <span
                                className={`${
                                    changeResult.isSignificant
                                        ? changeResult.isPositive
                                            ? 'text-success font-semibold'
                                            : 'text-danger font-semibold'
                                        : 'text-text-primary'
                                }`}
                            >
                                {changeResult.text}
                            </span>
                            {changeResult.isSignificant && changeResult.isPositive !== null && (
                                <span
                                    className={`flex-shrink-0 ${
                                        changeResult.isPositive ? 'text-success' : 'text-danger'
                                    }`}
                                >
                                    {changeResult.isPositive ? (
                                        <IconArrowUp className="w-4 h-4" />
                                    ) : (
                                        <IconTrendingDown className="w-4 h-4" />
                                    )}
                                </span>
                            )}
                        </div>
                    )
                )}
            </td>

            {/* Chart column */}
            {isBaseline ? (
                <td
                    className={`min-w-[400px] p-0 align-top text-center relative overflow-hidden ${
                        isAlternatingRow ? 'bg-bg-table' : 'bg-bg-light'
                    } ${isLastRow ? 'border-b border-border-bold' : ''}`}
                    style={{ height: `${CELL_HEIGHT}px`, maxHeight: `${CELL_HEIGHT}px` }}
                >
                    {chartRadius && chartRadius > 0 ? (
                        <div className="relative h-full">
                            <svg
                                viewBox={`0 0 ${VIEW_BOX_WIDTH} ${CHART_CELL_VIEW_BOX_HEIGHT}`}
                                preserveAspectRatio="none"
                                className="h-full w-full max-w-[1000px]"
                            >
                                <GridLines
                                    tickValues={getNiceTickValues(chartRadius)}
                                    scale={scale}
                                    height={CHART_CELL_VIEW_BOX_HEIGHT}
                                    viewBoxWidth={VIEW_BOX_WIDTH}
                                    zeroLineColor={colors.ZERO_LINE}
                                    gridLineColor={colors.BOUNDARY_LINES}
                                    zeroLineWidth={1.25}
                                    gridLineWidth={0.75}
                                    opacity={GRID_LINES_OPACITY}
                                />
                            </svg>
                        </div>
                    ) : (
                        <div className="flex items-center justify-center h-full text-muted text-xs">—</div>
                    )}
                </td>
            ) : (
                <ChartCell
                    variantResult={data as ExperimentVariantResult}
                    chartRadius={chartRadius}
                    metricIndex={metricIndex}
                    isAlternatingRow={isAlternatingRow}
                    isLastRow={isLastRow}
                />
            )}

            {/* Details column - only render for first row with rowspan */}
            {isFirstRow && (
                <td
                    className={`w-1/5 border-r border-border-bold p-3 align-top text-left relative overflow-hidden ${
                        !isLastMetric ? 'border-b' : ''
                    } ${isAlternatingRow ? 'bg-bg-table' : 'bg-bg-light'}`}
                    rowSpan={totalRows}
                    style={{
                        height: `${CELL_HEIGHT * totalRows}px`,
                        maxHeight: `${CELL_HEIGHT * totalRows}px`,
                    }}
                >
                    <DetailsButton metric={metric} setIsModalOpen={setIsModalOpen} />
                    <DetailsModal
                        isOpen={isModalOpen}
                        onClose={() => setIsModalOpen(false)}
                        metric={metric}
                        result={result}
                        experiment={experiment}
                        metricIndex={metricIndex}
                        isSecondary={isSecondary}
                    />
                </td>
            )}
        </tr>
    )
}
