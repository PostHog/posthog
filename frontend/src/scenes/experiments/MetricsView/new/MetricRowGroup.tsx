import { VariantRow } from './VariantRow'
import { ExperimentMetric, NewExperimentQueryResponse } from '~/queries/schema/schema-general'
import { Experiment, InsightType } from '~/types'
import { getNiceTickValues } from '../shared/utils'
import { MetricHeader } from '../shared/MetricHeader'
import { DetailsButton } from './DetailsButton'
import { DetailsModal } from './DetailsModal'
import { useState } from 'react'
import { humanFriendlyNumber } from 'lib/utils'
import { useChartColors } from '../shared/colors'
import { useAxisScale } from './useAxisScale'
import { GridLines } from './GridLines'
import {
    VIEW_BOX_WIDTH,
    SVG_EDGE_MARGIN,
    CHART_CELL_VIEW_BOX_HEIGHT,
    GRID_LINES_OPACITY,
    CELL_HEIGHT,
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

    // Get baseline from result.baseline and variants from result.variant_results
    const baselineResult = result?.baseline || null
    const variantResults = result?.variant_results || []

    // Calculate total rows for rowspan
    const totalRows = (baselineResult ? 1 : 0) + variantResults.length

    // Helper function to format baseline data
    const formatBaselineData = (): { formattedValue: string; rawValue: number | null } => {
        if (!baselineResult) {
            return { formattedValue: '—', rawValue: null }
        }
        const primaryValue = baselineResult.sum / baselineResult.number_of_samples
        const formattedValue =
            metric && 'metric_type' in metric && metric.metric_type === 'mean'
                ? primaryValue.toFixed(2)
                : `${(primaryValue * 100).toFixed(2)}%`
        return { formattedValue, rawValue: primaryValue }
    }

    const baselineData = formatBaselineData()

    return (
        <>
            {/* Baseline row with rowspan cells */}
            {baselineResult && (
                <tr
                    className="hover:bg-bg-hover group [&:last-child>td]:border-b-0"
                    style={{ height: `${CELL_HEIGHT}px`, maxHeight: `${CELL_HEIGHT}px` }}
                >
                    {/* Metric info column - with rowspan */}
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

                    {/* Baseline variant name */}
                    <td
                        className={`w-20 p-3 align-top text-left whitespace-nowrap overflow-hidden ${
                            isAlternatingRow ? 'bg-bg-table' : 'bg-bg-light'
                        } ${variantResults.length === 0 ? 'border-b border-border-bold' : ''}`}
                        style={{ height: `${CELL_HEIGHT}px`, maxHeight: `${CELL_HEIGHT}px` }}
                    >
                        <div className="text-sm text-text-primary whitespace-nowrap">
                            <span className="text-[#2563eb]">—</span> Baseline
                        </div>
                    </td>

                    {/* Baseline value */}
                    <td
                        className={`w-24 p-3 align-top text-left whitespace-nowrap overflow-hidden ${
                            isAlternatingRow ? 'bg-bg-table' : 'bg-bg-light'
                        } ${variantResults.length === 0 ? 'border-b border-border-bold' : ''}`}
                        style={{ height: `${CELL_HEIGHT}px`, maxHeight: `${CELL_HEIGHT}px` }}
                    >
                        <div className="text-sm">
                            <div className="text-text-primary">{baselineData.formattedValue}</div>
                            <div className="text-xs text-muted">
                                {baselineResult.sum} / {humanFriendlyNumber(baselineResult.number_of_samples || 0)}
                            </div>
                        </div>
                    </td>

                    {/* Baseline change (empty) */}
                    <td
                        className={`w-20 p-3 align-top text-left whitespace-nowrap overflow-hidden ${
                            isAlternatingRow ? 'bg-bg-table' : 'bg-bg-light'
                        } ${variantResults.length === 0 ? 'border-b border-border-bold' : ''}`}
                        style={{ height: `${CELL_HEIGHT}px`, maxHeight: `${CELL_HEIGHT}px` }}
                    >
                        <div className="text-xs text-muted" />
                    </td>

                    {/* Baseline chart (grid lines only) */}
                    <td
                        className={`min-w-[400px] p-0 align-top text-center relative overflow-hidden ${
                            isAlternatingRow ? 'bg-bg-table' : 'bg-bg-light'
                        } ${variantResults.length === 0 ? 'border-b border-border-bold' : ''}`}
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
                </tr>
            )}

            {/* Variant rows */}
            {variantResults.map((variantResult, index) => (
                <VariantRow
                    key={`${metricIndex}-${variantResult.key}`}
                    variantResult={variantResult}
                    isLastRow={index === variantResults.length - 1}
                    chartRadius={chartRadius}
                    metricIndex={metricIndex}
                    isAlternatingRow={isAlternatingRow}
                    hasRowspanCells={!baselineResult && index === 0}
                    metric={metric}
                    metricType={metricType}
                    isSecondary={isSecondary}
                    isLastMetric={isLastMetric}
                    totalRows={totalRows}
                    onDuplicateMetric={onDuplicateMetric}
                    canDuplicateMetric={canDuplicateMetric}
                    experiment={experiment}
                    result={result}
                />
            ))}
        </>
    )
}
