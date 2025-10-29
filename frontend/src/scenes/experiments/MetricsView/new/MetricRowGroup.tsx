import './MetricRowGroup.scss'

import { useActions, useValues } from 'kea'
import { useRef, useState } from 'react'
import { createPortal } from 'react-dom'

import { IconTrending } from '@posthog/icons'

import { FEATURE_FLAGS } from 'lib/constants'
import { IconTrendingDown } from 'lib/lemon-ui/icons'
import { humanFriendlyNumber } from 'lib/utils'
import { VariantTag } from 'scenes/experiments/ExperimentView/components'

import {
    ExperimentMetric,
    ExperimentStatsBaseValidated,
    NewExperimentQueryResponse,
} from '~/queries/schema/schema-general'
import { Experiment, InsightType } from '~/types'

import { experimentLogic } from '../../experimentLogic'
import { ChartEmptyState } from '../shared/ChartEmptyState'
import { ChartLoadingState } from '../shared/ChartLoadingState'
import { MetricHeader } from '../shared/MetricHeader'
import { useChartColors } from '../shared/colors'
import {
    type ExperimentVariantResult,
    formatDeltaPercent,
    formatMetricValue,
    getDelta,
    getMetricSubtitleValues,
    getNiceTickValues,
    hasValidationFailures,
    isDeltaPositive,
    isSignificant,
    isWinning,
} from '../shared/utils'
import { ChartCell } from './ChartCell'
import { DetailsButton } from './DetailsButton'
import { DetailsModal } from './DetailsModal'
import { GridLines } from './GridLines'
import { renderTooltipContent } from './MetricRowGroupTooltip'
import { TimeseriesModal } from './TimeseriesModal'
import {
    CELL_HEIGHT,
    CHART_CELL_VIEW_BOX_HEIGHT,
    GRID_LINES_OPACITY,
    SVG_EDGE_MARGIN,
    VIEW_BOX_WIDTH,
} from './constants'
import { useAxisScale } from './useAxisScale'

interface MetricRowGroupProps {
    metric: ExperimentMetric
    result: NewExperimentQueryResponse | null
    experiment: Experiment
    metricType: InsightType
    displayOrder: number
    axisRange: number
    isSecondary: boolean
    isLastMetric: boolean
    isAlternatingRow: boolean
    onDuplicateMetric?: () => void
    error?: any
    isLoading?: boolean
    hasMinimumExposureForResults?: boolean
    exposuresLoading?: boolean
    showDetailsModal: boolean
}

export function MetricRowGroup({
    metric,
    result,
    experiment,
    metricType,
    displayOrder,
    axisRange,
    isSecondary,
    isLastMetric,
    isAlternatingRow,
    onDuplicateMetric,
    error,
    isLoading,
    hasMinimumExposureForResults = true,
    exposuresLoading = false,
    showDetailsModal,
}: MetricRowGroupProps): JSX.Element {
    const [isModalOpen, setIsModalOpen] = useState(false)
    const [timeseriesModalState, setTimeseriesModalState] = useState<{
        isOpen: boolean
        variantResult: ExperimentVariantResult | null
    }>({
        isOpen: false,
        variantResult: null,
    })
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
    const scale = useAxisScale(axisRange, VIEW_BOX_WIDTH, SVG_EDGE_MARGIN)

    const { featureFlags } = useValues(experimentLogic)
    const { reportExperimentTimeseriesViewed } = useActions(experimentLogic)

    const timeseriesEnabled = featureFlags[FEATURE_FLAGS.EXPERIMENT_TIMESERIES] && experiment.stats_config?.timeseries

    // Calculate total rows for loading/error states
    const totalRows = isLoading || error || !result ? 1 : 1 + (result.variant_results?.length || 0)

    // Helper function to calculate tooltip position
    const calculateTooltipPosition = (
        chartCell: HTMLElement,
        variantResult: ExperimentVariantResult
    ): { x: number; y: number } | null => {
        if (!tooltipRef.current) {
            return null
        }

        const chartCellRect = chartCell.getBoundingClientRect()
        const tooltipRect = tooltipRef.current.getBoundingClientRect()

        // Calculate the delta position within the SVG
        const delta = getDelta(variantResult)
        const deltaX = scale(delta)

        // Convert SVG coordinates to pixel coordinates
        const svgToPixelRatio = chartCellRect.width / VIEW_BOX_WIDTH
        const deltaPixelX = deltaX * svgToPixelRatio

        // Calculate tooltip position: center it above the confidence interval bar
        let x = chartCellRect.left + deltaPixelX - tooltipRect.width / 2
        const y = chartCellRect.top - tooltipRect.height - 8

        // Keep tooltip within viewport bounds
        const padding = 8
        x = Math.max(padding, Math.min(x, window.innerWidth - tooltipRect.width - padding))

        return { x, y }
    }

    // Tooltip handlers
    const handleTooltipMouseEnter = (e: React.MouseEvent, variantResult: ExperimentVariantResult): void => {
        const chartCell = e.currentTarget.querySelector('[data-table-cell="chart"]') as HTMLElement
        if (!chartCell) {
            return
        }

        const position = calculateTooltipPosition(chartCell, variantResult)
        setTooltipState({
            isVisible: true,
            variantResult,
            position: position || { x: 0, y: 0 },
            isPositioned: !!position,
        })
    }

    const handleTooltipMouseLeave = (): void => {
        setTooltipState((prev) => ({
            ...prev,
            isVisible: false,
            variantResult: null,
            isPositioned: false,
        }))
    }

    const handleTooltipMouseMove = (e: React.MouseEvent, variantResult: ExperimentVariantResult): void => {
        // Only reposition if not already positioned
        if (!tooltipState.isPositioned) {
            const chartCell = e.currentTarget.querySelector('[data-table-cell="chart"]') as HTMLElement
            if (!chartCell) {
                return
            }

            const position = calculateTooltipPosition(chartCell, variantResult)
            if (position) {
                setTooltipState((prev) => ({
                    ...prev,
                    position,
                    isPositioned: true,
                }))
            }
        }
    }

    const handleTimeseriesClick = (variantResult: ExperimentVariantResult): void => {
        setTimeseriesModalState({
            isOpen: true,
            variantResult,
        })
        reportExperimentTimeseriesViewed(experiment.id, metric)
    }

    const handleTimeseriesModalClose = (): void => {
        setTimeseriesModalState({
            isOpen: false,
            variantResult: null,
        })
    }

    // Handle loading, API errors, or missing result
    // Note: If result has validation_failures but no API error, we'll show the data with inline warnings
    const hasResultWithValidationFailures = result && hasValidationFailures(result)

    if (isLoading || error || !result || (!hasMinimumExposureForResults && !hasResultWithValidationFailures)) {
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
                        displayOrder={displayOrder}
                        metric={metric}
                        metricType={metricType}
                        isPrimaryMetric={!isSecondary}
                        experiment={experiment}
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
                    {isLoading || exposuresLoading ? (
                        <ChartLoadingState height={CELL_HEIGHT} />
                    ) : (
                        <ChartEmptyState
                            height={CELL_HEIGHT}
                            experimentStarted={!!experiment.start_date}
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

    const ratioMetricLabel = (variant: ExperimentStatsBaseValidated, metric: ExperimentMetric): JSX.Element => {
        return (
            <div className="text-xs text-muted">
                {(() => {
                    const { numerator, denominator } = getMetricSubtitleValues(variant, metric)
                    return (
                        <>
                            {humanFriendlyNumber(numerator)} / {humanFriendlyNumber(denominator)}
                        </>
                    )
                })()}
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
                        {renderTooltipContent(experiment.id, tooltipState.variantResult, metric)}
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
                        displayOrder={displayOrder}
                        metric={metric}
                        metricType={metricType}
                        isPrimaryMetric={!isSecondary}
                        experiment={experiment}
                        onDuplicateMetricClick={() => onDuplicateMetric?.()}
                    />
                </td>

                {/* Variant name */}
                <td
                    className={`w-20 pt-1 pl-3 pr-3 pb-1 whitespace-nowrap overflow-hidden ${
                        isAlternatingRow ? 'bg-bg-table' : 'bg-bg-light'
                    } ${variantResults.length === 0 ? 'border-b' : ''}`}
                    style={{ height: `${CELL_HEIGHT}px`, maxHeight: `${CELL_HEIGHT}px` }}
                >
                    <VariantTag experimentId={experiment.id} variantKey={baselineResult.key} />
                </td>

                {/* Value */}
                <td
                    className={`w-24 pt-1 pl-3 pr-3 pb-1 text-left whitespace-nowrap overflow-hidden ${
                        isAlternatingRow ? 'bg-bg-table' : 'bg-bg-light'
                    } ${variantResults.length === 0 ? 'border-b' : ''}`}
                    style={{ height: `${CELL_HEIGHT}px`, maxHeight: `${CELL_HEIGHT}px` }}
                >
                    <div className="metric-cell">
                        <div>{formatMetricValue(baselineResult, metric)}</div>
                        {ratioMetricLabel(baselineResult, metric)}
                    </div>
                </td>

                {/* Change (empty for baseline) */}
                <td
                    className={`w-20 pt-1 pl-3 pr-3 pb-1 text-left whitespace-nowrap overflow-hidden ${
                        isAlternatingRow ? 'bg-bg-table' : 'bg-bg-light'
                    } ${variantResults.length === 0 ? 'border-b' : ''}`}
                    style={{ height: `${CELL_HEIGHT}px`, maxHeight: `${CELL_HEIGHT}px` }}
                >
                    <div />
                </td>

                {/* Details column - with rowspan */}
                <td
                    className={`pt-3 align-top relative overflow-hidden ${!isLastMetric ? 'border-b' : ''} ${
                        isAlternatingRow ? 'bg-bg-table' : 'bg-bg-light'
                    }`}
                    rowSpan={totalRows}
                    style={{
                        height: `${CELL_HEIGHT * totalRows}px`,
                        maxHeight: `${CELL_HEIGHT * totalRows}px`,
                    }}
                >
                    {showDetailsModal && (
                        <>
                            <div className="flex justify-end">
                                <DetailsButton metric={metric} setIsModalOpen={setIsModalOpen} />
                            </div>
                            <DetailsModal
                                isOpen={isModalOpen}
                                onClose={() => setIsModalOpen(false)}
                                metric={metric}
                                result={result}
                                experiment={experiment}
                            />
                        </>
                    )}
                </td>

                {/* Chart (grid lines only for baseline) */}
                <td
                    className={`p-0 align-top text-center relative overflow-hidden ${
                        isAlternatingRow ? 'bg-bg-table' : 'bg-bg-light'
                    } ${variantResults.length === 0 ? 'border-b' : ''}`}
                    style={{ height: `${CELL_HEIGHT}px`, maxHeight: `${CELL_HEIGHT}px` }}
                >
                    {axisRange && axisRange > 0 ? (
                        <div className="relative h-full">
                            <svg
                                viewBox={`0 0 ${VIEW_BOX_WIDTH} ${CHART_CELL_VIEW_BOX_HEIGHT}`}
                                preserveAspectRatio="none"
                                className="h-full w-full"
                            >
                                <GridLines
                                    tickValues={getNiceTickValues(axisRange)}
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
                const isLastRow = index === variantResults.length - 1
                const significant = isSignificant(variant)
                const deltaPositive = isDeltaPositive(variant)
                const winning = isWinning(variant, metric.goal)
                const deltaText = formatDeltaPercent(variant)

                return (
                    <tr
                        key={`${metric.uuid}-${variant.key}`}
                        className="hover:bg-bg-hover group [&:last-child>td]:border-b-0"
                        style={{ height: `${CELL_HEIGHT}px`, maxHeight: `${CELL_HEIGHT}px` }}
                        onMouseEnter={(e) => handleTooltipMouseEnter(e, variant)}
                        onMouseLeave={handleTooltipMouseLeave}
                        onMouseMove={(e) => handleTooltipMouseMove(e, variant)}
                    >
                        {/* Variant name */}
                        <td
                            className={`w-20 pt-1 pl-3 pr-3 pb-1 text-left whitespace-nowrap overflow-hidden ${
                                isAlternatingRow ? 'bg-bg-table' : 'bg-bg-light'
                            } ${isLastRow ? 'border-b' : ''}`}
                            style={{ height: `${CELL_HEIGHT}px`, maxHeight: `${CELL_HEIGHT}px` }}
                        >
                            <VariantTag experimentId={experiment.id} variantKey={variant.key} />
                        </td>

                        {/* Value */}
                        <td
                            className={`w-24 pt-1 pl-3 pr-3 pb-1 text-left whitespace-nowrap overflow-hidden ${
                                isAlternatingRow ? 'bg-bg-table' : 'bg-bg-light'
                            } ${isLastRow ? 'border-b' : ''}`}
                            style={{ height: `${CELL_HEIGHT}px`, maxHeight: `${CELL_HEIGHT}px` }}
                        >
                            <div className="metric-cell">
                                <div>{formatMetricValue(variant, metric)}</div>
                                {ratioMetricLabel(variant, metric)}
                            </div>
                        </td>

                        {/* Delta */}
                        <td
                            className={`w-20 pt-1 pl-3 pr-3 pb-1 text-left whitespace-nowrap overflow-hidden ${
                                isAlternatingRow ? 'bg-bg-table' : 'bg-bg-light'
                            } ${isLastRow ? 'border-b' : ''}`}
                            style={{ height: `${CELL_HEIGHT}px`, maxHeight: `${CELL_HEIGHT}px` }}
                        >
                            <div className="flex items-center gap-1">
                                <span
                                    className={`${
                                        significant
                                            ? winning
                                                ? 'metric-cell text-success font-bold'
                                                : 'metric-cell text-danger font-bold'
                                            : 'metric-cell'
                                    }`}
                                >
                                    {deltaText}
                                </span>
                                {significant && deltaPositive !== undefined && (
                                    <span className={`flex-shrink-0 ${winning ? 'text-success' : 'text-danger'}`}>
                                        {deltaPositive ? (
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
                            metric={metric}
                            axisRange={axisRange}
                            metricUuid={metric.uuid}
                            isAlternatingRow={isAlternatingRow}
                            isLastRow={isLastRow}
                            isSecondary={isSecondary}
                            onTimeseriesClick={timeseriesEnabled ? () => handleTimeseriesClick(variant) : undefined}
                        />
                    </tr>
                )
            })}
            {timeseriesModalState.variantResult && (
                <TimeseriesModal
                    isOpen={timeseriesModalState.isOpen}
                    onClose={handleTimeseriesModalClose}
                    metric={metric}
                    variantResult={timeseriesModalState.variantResult}
                    experiment={experiment}
                />
            )}
        </>
    )
}
