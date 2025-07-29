import { IconTrending } from '@posthog/icons'
import { IconTrendingDown } from 'lib/lemon-ui/icons'
import { humanFriendlyNumber } from 'lib/utils'
import { useState } from 'react'
import { ExperimentMetric, NewExperimentQueryResponse, ExperimentMetricType } from '~/queries/schema/schema-general'
import { Experiment, InsightType } from '~/types'
import { ChartEmptyState } from '../shared/ChartEmptyState'
import { ChartLoadingState } from '../shared/ChartLoadingState'
import { useChartColors } from '../shared/colors'
import { MetricHeader } from '../shared/MetricHeader'
import { formatPercentageChange, getNiceTickValues } from '../shared/utils'
import { MetricHeader } from '../shared/MetricHeader'
import { DetailsButton } from './DetailsButton'
import { DetailsModal } from './DetailsModal'
import { useState, useRef, useEffect } from 'react'
import { humanFriendlyNumber } from 'lib/utils'
import { useChartColors } from '../shared/colors'
import { useAxisScale } from './useAxisScale'
import { GridLines } from './GridLines'
import { ChartCell } from './ChartCell'
import { createPortal } from 'react-dom'
import { LemonTag } from 'lib/lemon-ui/LemonTag'
import {
    formatChanceToWin,
    formatPValue,
    getIntervalLabel,
    getVariantInterval,
    isBayesianResult,
    type ExperimentVariantResult,
} from '../shared/utils'
import { IconTrendingDown } from 'lib/lemon-ui/icons'
import { IconTrending } from '@posthog/icons'
import { ChartLoadingState } from '../shared/ChartLoadingState'
import { ChartEmptyState } from '../shared/ChartEmptyState'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import {
    CELL_HEIGHT,
    CHART_CELL_VIEW_BOX_HEIGHT,
    GRID_LINES_OPACITY,
    SVG_EDGE_MARGIN,
    VIEW_BOX_WIDTH,
} from './constants'
import { DetailsButton } from './DetailsButton'
import { DetailsModal } from './DetailsModal'
import { GridLines } from './GridLines'
import { useAxisScale } from './useAxisScale'

interface MetricRowGroupProps {
    metric: ExperimentMetric
    result: NewExperimentQueryResponse | null
    experiment: Experiment
    metricType: InsightType
    metricIndex: number
    chartRadius: number
    isSecondary: boolean
    isLastMetric: boolean
    isAlternatingRow: boolean
    onDuplicateMetric?: () => void
    canDuplicateMetric?: boolean
    error?: any
    isLoading?: boolean
    hasMinimumExposureForResults?: boolean
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
    error,
    isLoading,
    hasMinimumExposureForResults = true,
}: MetricRowGroupProps): JSX.Element {
    const [isModalOpen, setIsModalOpen] = useState(false)
    const [tooltipState, setTooltipState] = useState<{
        isVisible: boolean
        variantResult: ExperimentVariantResult | null
        position: { x: number; y: number }
        isPositioned: boolean
    }>({
        isVisible: false,
        variantResult: null,
        position: { x: 0, y: 0 },
        isPositioned: false,
    })
    const tooltipRef = useRef<HTMLDivElement>(null)
    const colors = useChartColors()
    const scale = useAxisScale(chartRadius, VIEW_BOX_WIDTH, SVG_EDGE_MARGIN)

    // Calculate total rows for loading/error states
    const totalRows = isLoading || error || !result ? 1 : 1 + (result.variant_results?.length || 0)

    // Helper function to format data
    const formatData = (data: any): string => {
        const primaryValue = data.sum / data.number_of_samples
        return metric && 'metric_type' in metric && metric.metric_type === 'mean'
            ? primaryValue.toFixed(2)
            : `${(primaryValue * 100).toFixed(2)}%`
    }

    // Helper function to get tooltip content for value cells
    const getValueTooltipContent = (): string => {
        if (!metric || !('metric_type' in metric)) {
            return ''
        }

        return metric.metric_type === ExperimentMetricType.MEAN
            ? 'Total value / exposures'
            : 'Total conversions / exposures'
    }

    // Tooltip handlers
    const handleTooltipMouseEnter = (variantResult: ExperimentVariantResult): void => {
        setTooltipState((prev) => ({
            ...prev,
            isVisible: true,
            variantResult,
            isPositioned: false,
        }))
    }

    const handleTooltipMouseLeave = (): void => {
        setTooltipState((prev) => ({
            ...prev,
            isVisible: false,
            variantResult: null,
            isPositioned: false,
        }))
    }

    const handleTooltipMouseMove = (e: React.MouseEvent, containerRect: DOMRect): void => {
        // Only position the tooltip if it hasn't been positioned yet
        if (tooltipRef.current && !tooltipState.isPositioned) {
            const tooltipRect = tooltipRef.current.getBoundingClientRect()

            // Position tooltip horizontally at mouse cursor
            let x = e.clientX - tooltipRect.width / 2
            const y = containerRect.top - tooltipRect.height - 8

            // Keep tooltip within viewport bounds
            const padding = 8
            if (x < padding) {
                x = padding
            } else if (x + tooltipRect.width > window.innerWidth - padding) {
                x = window.innerWidth - tooltipRect.width - padding
            }

            setTooltipState((prev) => ({
                ...prev,
                position: { x, y },
                isPositioned: true,
            }))
        }
    }

    // Effect to handle initial tooltip positioning
    useEffect(() => {
        if (tooltipState.isVisible && tooltipState.variantResult && tooltipRef.current) {
            // Initial positioning will be handled by mouse move
        }
    }, [tooltipState.isVisible, tooltipState.variantResult])

    // Handle loading or error states
    if (isLoading || error || !result || !hasMinimumExposureForResults) {
        return (
            <tr
                className="hover:bg-bg-hover group [&:last-child>td]:border-b-0"
                style={{ height: `${CELL_HEIGHT}px`, maxHeight: `${CELL_HEIGHT}px` }}
            >
                {/* Metric column - always visible */}
                <td
                    className={`w-1/5 border-r p-3 align-top text-left relative overflow-hidden ${
                        !isLastMetric ? 'border-b' : ''
                    } ${isAlternatingRow ? 'bg-bg-table' : 'bg-bg-light'}`}
                    style={{
                        height: `${CELL_HEIGHT}px`,
                        maxHeight: `${CELL_HEIGHT}px`,
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

                {/* Combined columns for loading/error state */}
                <td
                    colSpan={5}
                    className={`p-3 text-center ${isAlternatingRow ? 'bg-bg-table' : 'bg-bg-light'} ${
                        !isLastMetric ? 'border-b' : ''
                    }`}
                    style={{ height: `${CELL_HEIGHT}px`, maxHeight: `${CELL_HEIGHT}px` }}
                >
                    {isLoading ? (
                        <ChartLoadingState height={CELL_HEIGHT} />
                    ) : (
                        <ChartEmptyState
                            height={CELL_HEIGHT}
                            experimentStarted={!!experiment.start_date}
                            hasMinimumExposure={hasMinimumExposureForResults}
                            metric={metric}
                            error={error}
                        />
                    )}
                </td>
            </tr>
        )
    }

    // At this point, we know result is defined, so we can safely access its properties
    const baselineResult = result.baseline
    const variantResults = result.variant_results || []

    // Render tooltip content
    const renderTooltipContent = (variantResult: ExperimentVariantResult): JSX.Element => {
        const interval = getVariantInterval(variantResult)
        const [lower, upper] = interval ? [interval[0], interval[1]] : [0, 0]
        const intervalPercent = interval ? `[${(lower * 100).toFixed(2)}%, ${(upper * 100).toFixed(2)}%]` : 'N/A'
        const intervalLabel = getIntervalLabel(variantResult)

        return (
            <div className="flex flex-col gap-1">
                <div className="flex justify-between items-center">
                    <div className="font-semibold">{variantResult.key}</div>
                    {variantResult.key !== 'control' && (
                        <LemonTag
                            type={
                                !variantResult.significant
                                    ? 'muted'
                                    : (() => {
                                          const interval = getVariantInterval(variantResult)
                                          const deltaPercent = interval ? ((interval[0] + interval[1]) / 2) * 100 : 0
                                          return deltaPercent > 0 ? 'success' : 'danger'
                                      })()
                            }
                            size="medium"
                        >
                            {!variantResult.significant
                                ? 'Not significant'
                                : (() => {
                                      const interval = getVariantInterval(variantResult)
                                      const deltaPercent = interval ? ((interval[0] + interval[1]) / 2) * 100 : 0
                                      return deltaPercent > 0 ? 'Won' : 'Lost'
                                  })()}
                        </LemonTag>
                    )}
                </div>

                <div className="flex justify-between items-center">
                    <span className="text-muted-alt font-semibold">Total value:</span>
                    <span className="font-semibold">{variantResult.sum}</span>
                </div>

                <div className="flex justify-between items-center">
                    <span className="text-muted-alt font-semibold">Exposures:</span>
                    <span className="font-semibold">{variantResult.number_of_samples}</span>
                </div>

                {isBayesianResult(variantResult) ? (
                    <div className="flex justify-between items-center">
                        <span className="text-muted-alt font-semibold">Chance to win:</span>
                        <span className="font-semibold">{formatChanceToWin(variantResult.chance_to_win)}</span>
                    </div>
                ) : (
                    <div className="flex justify-between items-center">
                        <span className="text-muted-alt font-semibold">P-value:</span>
                        <span className="font-semibold">{formatPValue(variantResult.p_value)}</span>
                    </div>
                )}

                <div className="flex justify-between items-center">
                    <span className="text-muted-alt font-semibold">Delta:</span>
                    <span className="font-semibold">
                        {variantResult.key === 'control' ? (
                            <em className="text-muted-alt">Baseline</em>
                        ) : (
                            (() => {
                                const deltaPercent = interval ? ((lower + upper) / 2) * 100 : 0
                                const isPositive = deltaPercent > 0
                                return (
                                    <span className={isPositive ? 'text-success' : 'text-danger'}>
                                        {`${isPositive ? '+' : ''}${deltaPercent.toFixed(2)}%`}
                                    </span>
                                )
                            })()
                        )}
                    </span>
                </div>

                <div className="flex justify-between items-center">
                    <span className="text-muted-alt font-semibold">{intervalLabel}:</span>
                    <span className="font-semibold">{intervalPercent}</span>
                </div>
            </div>
        )
    }

    return (
        <>
            {/* Tooltip portal */}
            {tooltipState.isVisible &&
                tooltipState.variantResult &&
                createPortal(
                    <div
                        ref={tooltipRef}
                        className="fixed bg-bg-light border border-border px-3 py-2 rounded-md text-[13px] shadow-md z-[100] min-w-[280px]"
                        style={{
                            left: tooltipState.position.x,
                            top: tooltipState.position.y,
                            visibility: tooltipState.isPositioned ? 'visible' : 'hidden',
                        }}
                    >
                        {renderTooltipContent(tooltipState.variantResult)}
                    </div>,
                    document.body
                )}

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
                    className={`w-20 pt-1 pl-3 pr-3 pb-1 text-xs font-semibold text-left whitespace-nowrap overflow-hidden ${
                        isAlternatingRow ? 'bg-bg-table' : 'bg-bg-light'
                    } ${variantResults.length === 0 ? 'border-b' : ''}`}
                    style={{ height: `${CELL_HEIGHT}px`, maxHeight: `${CELL_HEIGHT}px` }}
                >
                    <div className="text-xs font-semibold">{baselineResult.key}</div>
                </td>

                {/* Value */}
                <td
                    className={`w-24 pt-1 pl-3 pr-3 pb-1 text-left whitespace-nowrap overflow-hidden ${
                        isAlternatingRow ? 'bg-bg-table' : 'bg-bg-light'
                    } ${variantResults.length === 0 ? 'border-b' : ''}`}
                    style={{ height: `${CELL_HEIGHT}px`, maxHeight: `${CELL_HEIGHT}px` }}
                >
                    <Tooltip title={getValueTooltipContent()}>
                        <div className="text-sm">
                            <div className="text-text-primary">{formatData(baselineResult)}</div>
                            <div className="text-xs text-muted">
                                {humanFriendlyNumber(baselineResult.sum)} /{' '}
                                {humanFriendlyNumber(baselineResult.number_of_samples || 0)}
                            </div>
                        </div>
                    </Tooltip>
                </td>

                {/* Change (empty for baseline) */}
                <td
                    className={`w-20 pt-1 pl-3 pr-3 pb-1 text-left whitespace-nowrap overflow-hidden ${
                        isAlternatingRow ? 'bg-bg-table' : 'bg-bg-light'
                    } ${variantResults.length === 0 ? 'border-b' : ''}`}
                    style={{ height: `${CELL_HEIGHT}px`, maxHeight: `${CELL_HEIGHT}px` }}
                >
                    <div className="text-xs text-muted" />
                </td>

                {/* Details column - with rowspan */}
                <td
                    className={`p-3 align-top relative overflow-hidden ${!isLastMetric ? 'border-b' : ''} ${
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
                                className="h-full w-full"
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
                        onMouseEnter={() => handleTooltipMouseEnter(variant)}
                        onMouseLeave={handleTooltipMouseLeave}
                        onMouseMove={(e) => {
                            const rect = e.currentTarget.getBoundingClientRect()
                            handleTooltipMouseMove(e, rect)
                        }}
                    >
                        {/* Variant name */}
                        <td
                            className={`w-20 pt-1 pl-3 pr-3 pb-1 text-left whitespace-nowrap overflow-hidden ${
                                isAlternatingRow ? 'bg-bg-table' : 'bg-bg-light'
                            } ${isLastRow ? 'border-b' : ''}`}
                            style={{ height: `${CELL_HEIGHT}px`, maxHeight: `${CELL_HEIGHT}px` }}
                        >
                            <div className="text-xs font-semibold whitespace-nowrap">{variant.key}</div>
                        </td>

                        {/* Value */}
                        <td
                            className={`w-24 pt-1 pl-3 pr-3 pb-1 text-left whitespace-nowrap overflow-hidden ${
                                isAlternatingRow ? 'bg-bg-table' : 'bg-bg-light'
                            } ${isLastRow ? 'border-b' : ''}`}
                            style={{ height: `${CELL_HEIGHT}px`, maxHeight: `${CELL_HEIGHT}px` }}
                        >
                            <Tooltip title={getValueTooltipContent()}>
                                <div className="text-sm">
                                    <div className="text-text-primary">{formatData(variant)}</div>
                                    <div className="text-xs text-muted">
                                        {humanFriendlyNumber(variant.sum)} /{' '}
                                        {humanFriendlyNumber(variant.number_of_samples || 0)}
                                    </div>
                                </div>
                            </Tooltip>
                        </td>

                        {/* Change */}
                        <td
                            className={`w-20 pt-1 pl-3 pr-3 pb-1 text-left whitespace-nowrap overflow-hidden ${
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
                            isSecondary={isSecondary}
                        />
                    </tr>
                )
            })}
        </>
    )
}
