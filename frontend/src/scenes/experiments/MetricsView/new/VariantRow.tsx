import { humanFriendlyNumber } from 'lib/utils'
import { ChartCell } from './ChartCell'
import { type ExperimentVariantResult, formatPercentageChange } from '../shared/utils'
import { IconArrowUp, IconTrendingDown } from 'lib/lemon-ui/icons'
import { ExperimentMetric, NewExperimentQueryResponse } from '~/queries/schema/schema-general'
import { Experiment, InsightType } from '~/types'
import { CELL_HEIGHT } from './constants'
import { MetricHeader } from '../shared/MetricHeader'
import { DetailsButton } from './DetailsButton'
import { DetailsModal } from './DetailsModal'
import { useState } from 'react'

interface VariantRowProps {
    variantResult: ExperimentVariantResult
    isLastRow: boolean
    chartRadius: number
    metricIndex: number
    isAlternatingRow: boolean
    hasRowspanCells?: boolean // True if this variant row needs to render the metric and details cells (when no baseline)
    metric?: ExperimentMetric // Only needed if hasRowspanCells is true
    metricType?: InsightType // Only needed if hasRowspanCells is true
    isSecondary?: boolean // Only needed if hasRowspanCells is true
    isLastMetric?: boolean // Only needed if hasRowspanCells is true
    totalRows?: number // Only needed if hasRowspanCells is true
    onDuplicateMetric?: () => void // Only needed if hasRowspanCells is true
    canDuplicateMetric?: boolean // Only needed if hasRowspanCells is true
    experiment?: Experiment // Only needed if hasRowspanCells is true
    result?: NewExperimentQueryResponse // Only needed if hasRowspanCells is true
}

export function VariantRow({
    variantResult,
    isLastRow,
    chartRadius,
    metricIndex,
    isAlternatingRow,
    hasRowspanCells = false,
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

    // Helper function to format variant data
    const formatVariantData = (): { formattedValue: string } => {
        const primaryValue = variantResult.sum / variantResult.number_of_samples
        const formattedValue =
            metric && 'metric_type' in metric && metric.metric_type === 'mean'
                ? primaryValue.toFixed(2)
                : `${(primaryValue * 100).toFixed(2)}%`
        return { formattedValue }
    }

    const { formattedValue } = formatVariantData()
    const changeResult = formatPercentageChange(variantResult)

    return (
        <tr
            className="hover:bg-bg-hover group [&:last-child>td]:border-b-0"
            style={{ height: `${CELL_HEIGHT}px`, maxHeight: `${CELL_HEIGHT}px` }}
        >
            {/* Metric column - only render if hasRowspanCells (no baseline case) */}
            {hasRowspanCells && metric && metricType && (
                <td
                    className={`w-1/5 border-r border-border-bold p-3 align-top text-left relative overflow-hidden ${
                        !isLastMetric ? 'border-b' : ''
                    } ${isAlternatingRow ? 'bg-bg-table' : 'bg-bg-light'}`}
                    rowSpan={totalRows}
                    style={{
                        height: `${CELL_HEIGHT * (totalRows || 1)}px`,
                        maxHeight: `${CELL_HEIGHT * (totalRows || 1)}px`,
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
                    <span className="text-[#2563eb]">—</span> {variantResult.key}
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
                        {variantResult.sum} / {humanFriendlyNumber(variantResult.number_of_samples || 0)}
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
                        <span className={`flex-shrink-0 ${changeResult.isPositive ? 'text-success' : 'text-danger'}`}>
                            {changeResult.isPositive ? (
                                <IconArrowUp className="w-4 h-4" />
                            ) : (
                                <IconTrendingDown className="w-4 h-4" />
                            )}
                        </span>
                    )}
                </div>
            </td>

            {/* Chart column */}
            <ChartCell
                variantResult={variantResult}
                chartRadius={chartRadius}
                metricIndex={metricIndex}
                isAlternatingRow={isAlternatingRow}
                isLastRow={isLastRow}
            />

            {/* Details column - only render if hasRowspanCells (no baseline case) */}
            {hasRowspanCells && metric && experiment && result && (
                <td
                    className={`w-1/5 border-r border-border-bold p-3 align-top text-left relative overflow-hidden ${
                        !isLastMetric ? 'border-b' : ''
                    } ${isAlternatingRow ? 'bg-bg-table' : 'bg-bg-light'}`}
                    rowSpan={totalRows}
                    style={{
                        height: `${CELL_HEIGHT * (totalRows || 1)}px`,
                        maxHeight: `${CELL_HEIGHT * (totalRows || 1)}px`,
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
                        isSecondary={isSecondary || false}
                    />
                </td>
            )}
        </tr>
    )
}
