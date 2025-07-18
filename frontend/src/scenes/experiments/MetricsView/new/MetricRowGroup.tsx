import { ExperimentMetric, NewExperimentQueryResponse } from '~/queries/schema/schema-general'
import { Experiment, InsightType } from '~/types'
import { formatPercentageChange, getNiceTickValues } from '../shared/utils'
import { MetricHeader } from '../shared/MetricHeader'
import { DetailsButton } from './DetailsButton'
import { DetailsModal } from './DetailsModal'
import { useState } from 'react'
import { humanFriendlyNumber } from 'lib/utils'
import { useChartColors } from '../shared/colors'
import { useAxisScale } from './useAxisScale'
import { GridLines } from './GridLines'
import { ChartCell } from './ChartCell'
import { IconTrendingDown } from 'lib/lemon-ui/icons'
import { IconTrending } from '@posthog/icons'
import {
    CELL_HEIGHT,
    VIEW_BOX_WIDTH,
    SVG_EDGE_MARGIN,
    CHART_CELL_VIEW_BOX_HEIGHT,
    GRID_LINES_OPACITY,
} from './constants'

interface MetricRowGroupProps {
    metric: ExperimentMetric
    result: NewExperimentQueryResponse
    experiment: Experiment
    metricType: InsightType
    metricIndex: number
    chartRadius: number
    isSecondary: boolean
    isLastMetric: boolean
    isAlternatingRow: boolean
    onDuplicateMetric?: () => void
    canDuplicateMetric?: boolean
}

export function MetricRowGroup({
    metric,
    result,
    experiment,
    metricType,
    metricIndex,
    chartRadius,
    isSecondary,
    isLastMetric,
    isAlternatingRow,
    onDuplicateMetric,
    canDuplicateMetric,
}: MetricRowGroupProps): JSX.Element {
    const [isModalOpen, setIsModalOpen] = useState(false)
    const colors = useChartColors()
    const scale = useAxisScale(chartRadius, VIEW_BOX_WIDTH, SVG_EDGE_MARGIN)

    const baselineResult = result.baseline
    const variantResults = result.variant_results || []
    const totalRows = 1 + variantResults.length

    // Helper function to format data
    const formatData = (data: any): string => {
        const primaryValue = data.sum / data.number_of_samples
        return metric && 'metric_type' in metric && metric.metric_type === 'mean'
            ? primaryValue.toFixed(2)
            : `${(primaryValue * 100).toFixed(2)}%`
    }

    return (
        <>
            {/* Baseline row */}
            <tr
                className="hover:bg-bg-hover group [&:last-child>td]:border-b-0"
                style={{ height: `${CELL_HEIGHT}px`, maxHeight: `${CELL_HEIGHT}px` }}
            >
                {/* Metric column - with rowspan */}
                <td
                    className={`w-1/5 border-r p-3 align-top text-left relative overflow-hidden ${
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

                {/* Variant name */}
                <td
                    className={`w-20 p-3 text-xs font-semibold text-left whitespace-nowrap overflow-hidden ${
                        isAlternatingRow ? 'bg-bg-table' : 'bg-bg-light'
                    } ${variantResults.length === 0 ? 'border-b' : ''}`}
                    style={{ height: `${CELL_HEIGHT}px`, maxHeight: `${CELL_HEIGHT}px` }}
                >
                    <div className="text-xs font-semibold">{baselineResult.key}</div>
                </td>

                {/* Value */}
                <td
                    className={`w-24 p-3 text-left whitespace-nowrap overflow-hidden ${
                        isAlternatingRow ? 'bg-bg-table' : 'bg-bg-light'
                    } ${variantResults.length === 0 ? 'border-b' : ''}`}
                    style={{ height: `${CELL_HEIGHT}px`, maxHeight: `${CELL_HEIGHT}px` }}
                >
                    <div className="text-sm">
                        <div className="text-text-primary">{formatData(baselineResult)}</div>
                        <div className="text-xs text-muted">
                            {baselineResult.sum} / {humanFriendlyNumber(baselineResult.number_of_samples || 0)}
                        </div>
                    </div>
                </td>

                {/* Change (empty for baseline) */}
                <td
                    className={`w-20 p-3 text-left whitespace-nowrap overflow-hidden ${
                        isAlternatingRow ? 'bg-bg-table' : 'bg-bg-light'
                    } ${variantResults.length === 0 ? 'border-b' : ''}`}
                    style={{ height: `${CELL_HEIGHT}px`, maxHeight: `${CELL_HEIGHT}px` }}
                >
                    <div className="text-xs text-muted" />
                </td>

                {/* Chart (grid lines only for baseline) */}
                <td
                    className={`min-w-[400px] w-full p-0 align-top text-center relative overflow-hidden ${
                        isAlternatingRow ? 'bg-bg-table' : 'bg-bg-light'
                    } ${variantResults.length === 0 ? 'border-b' : ''}`}
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

                {/* Details column - with rowspan */}
                <td
                    className={`w-1/5 p-3 align-top relative overflow-hidden ${!isLastMetric ? 'border-b' : ''} ${
                        isAlternatingRow ? 'bg-bg-table' : 'bg-bg-light'
                    }`}
                    rowSpan={totalRows}
                    style={{
                        height: `${CELL_HEIGHT * totalRows}px`,
                        maxHeight: `${CELL_HEIGHT * totalRows}px`,
                    }}
                >
                    <div className="flex justify-end">
                        <DetailsButton metric={metric} setIsModalOpen={setIsModalOpen} />
                    </div>
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
            </tr>

            {/* Variant rows */}
            {variantResults.map((variant, index) => {
                const changeResult = formatPercentageChange(variant)
                const isLastRow = index === variantResults.length - 1

                return (
                    <tr
                        key={`${metricIndex}-${variant.key}`}
                        className="hover:bg-bg-hover group [&:last-child>td]:border-b-0"
                        style={{ height: `${CELL_HEIGHT}px`, maxHeight: `${CELL_HEIGHT}px` }}
                    >
                        {/* Variant name */}
                        <td
                            className={`w-20 p-3 text-left whitespace-nowrap overflow-hidden ${
                                isAlternatingRow ? 'bg-bg-table' : 'bg-bg-light'
                            } ${isLastRow ? 'border-b' : ''}`}
                            style={{ height: `${CELL_HEIGHT}px`, maxHeight: `${CELL_HEIGHT}px` }}
                        >
                            <div className="text-xs font-semibold whitespace-nowrap">{variant.key}</div>
                        </td>

                        {/* Value */}
                        <td
                            className={`w-24 p-3 text-left whitespace-nowrap overflow-hidden ${
                                isAlternatingRow ? 'bg-bg-table' : 'bg-bg-light'
                            } ${isLastRow ? 'border-b' : ''}`}
                            style={{ height: `${CELL_HEIGHT}px`, maxHeight: `${CELL_HEIGHT}px` }}
                        >
                            <div className="text-sm">
                                <div className="text-text-primary">{formatData(variant)}</div>
                                <div className="text-xs text-muted">
                                    {variant.sum} / {humanFriendlyNumber(variant.number_of_samples || 0)}
                                </div>
                            </div>
                        </td>

                        {/* Change */}
                        <td
                            className={`w-20 p-3 text-left whitespace-nowrap overflow-hidden ${
                                isAlternatingRow ? 'bg-bg-table' : 'bg-bg-light'
                            } ${isLastRow ? 'border-b' : ''}`}
                            style={{ height: `${CELL_HEIGHT}px`, maxHeight: `${CELL_HEIGHT}px` }}
                        >
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
                                            <IconTrending className="w-4 h-4" />
                                        ) : (
                                            <IconTrendingDown className="w-4 h-4" />
                                        )}
                                    </span>
                                )}
                            </div>
                        </td>

                        {/* Chart */}
                        <ChartCell
                            variantResult={variant}
                            chartRadius={chartRadius}
                            metricIndex={metricIndex}
                            isAlternatingRow={isAlternatingRow}
                            isLastRow={isLastRow}
                        />
                    </tr>
                )
            })}
        </>
    )
}
