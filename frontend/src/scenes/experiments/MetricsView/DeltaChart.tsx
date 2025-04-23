import { IconGraph } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { FEATURE_FLAGS } from 'lib/constants'
import { createContext, useContext, useState } from 'react'

import { Experiment, ExperimentIdType, FunnelExperimentVariant, InsightType, TrendExperimentVariant } from '~/types'

import { experimentLogic } from '../experimentLogic'
import { VariantTag } from '../ExperimentView/components'
import { ChartEmptyState } from './ChartEmptyState'
import { ChartLoadingState } from './ChartLoadingState'
import { ChartModal } from './ChartModal'
import { useChartColors } from './colors'
import { GridLines } from './GridLines'
import { MetricHeader } from './MetricHeader'
import { MetricsChartLayout } from './MetricsChartLayout'
import { SignificanceHighlight } from './SignificanceHighlight'
import { VariantTooltip } from './VariantTooltip'
import { generateViolinPath } from './violinUtils'

// Chart configuration types
type ChartDimensions = {
    barHeight: number
    barPadding: number
    viewBoxWidth: number
    horizontalPadding: number
    chartHeight: number
}

type TooltipState = {
    tooltipData: { x: number; y: number; variant: string } | null
    setTooltipData: (data: { x: number; y: number; variant: string } | null) => void
    emptyStateTooltipVisible: boolean
    setEmptyStateTooltipVisible: (visible: boolean) => void
    tooltipPosition: { x: number; y: number }
    setTooltipPosition: (position: { x: number; y: number }) => void
}

// Context containing all necessary data for child components
type DeltaChartContextType = {
    // Chart properties
    result: any
    error: any
    metricIndex: number
    isSecondary: boolean
    metricType: InsightType
    metric: any
    tickValues: number[]
    chartBound: number

    // Experiment data
    experimentId: ExperimentIdType
    experiment: Experiment
    variants: FunnelExperimentVariant[] | TrendExperimentVariant[]
    hasMinimumExposureForResults: boolean
    featureFlags: Record<string, any>
    primaryMetricsLengthWithSharedMetrics: number

    // Data transformation functions
    valueToX: (value: number) => number
    credibleIntervalForVariant: (result: any, variantKey: string, metricType: InsightType) => [number, number] | null
    conversionRateForVariant: (result: any, variantKey: string) => number | null
    countDataForVariant: (result: any, variantKey: string) => any
    exposureCountDataForVariant: (result: any, variantKey: string) => any

    // Chart dimensions
    dimensions: ChartDimensions

    // UI state & actions
    isModalOpen: boolean
    setIsModalOpen: (isOpen: boolean) => void
    resultsLoading: boolean
    openVariantDeltaTimeseriesModal: () => void

    // Colors
    colors: ReturnType<typeof useChartColors>

    // Tooltip state
    tooltip: TooltipState
}

// Create context with default values
const DeltaChartContext = createContext<DeltaChartContextType | null>(null)

// Custom hook to use the chart context
function useDeltaChartContext(): DeltaChartContextType {
    const context = useContext(DeltaChartContext)
    if (!context) {
        throw new Error('useDeltaChartContext must be used within a DeltaChartContextProvider')
    }
    return context
}

// Custom hook for calculating dimensions based on variant count
function useChartDimensions(variants: any[]): ChartDimensions {
    const getScaleAddition = (variantCount: number): number => {
        if (variantCount < 3) {
            return 6
        }
        if (variantCount < 4) {
            return 3
        }
        if (variantCount < 5) {
            return 1
        }
        return 0
    }

    const scaleAddition = getScaleAddition(variants.length)
    const barHeight = 10 + scaleAddition
    const barPadding = 10 + scaleAddition
    const viewBoxWidth = 800
    const horizontalPadding = 20

    // Calculate the chart height
    const chartHeight = barPadding + (barHeight + barPadding) * variants.length

    return {
        barHeight,
        barPadding,
        viewBoxWidth,
        horizontalPadding,
        chartHeight,
    }
}

// Individual variant bar component
function VariantBar({ variant, index }: { variant: any; index: number }): JSX.Element {
    const {
        result,
        metricType,
        dimensions,
        valueToX,
        experimentId,
        featureFlags,
        colors,
        tooltip: { setTooltipData },
        credibleIntervalForVariant,
        conversionRateForVariant,
        metricIndex,
        isSecondary,
        openVariantDeltaTimeseriesModal,
    } = useDeltaChartContext()

    const { barHeight, barPadding } = dimensions

    // Calculate interval and delta
    const interval = credibleIntervalForVariant(result, variant.key, metricType)
    const [lower, upper] = interval ? [interval[0] / 100, interval[1] / 100] : [0, 0]

    let delta: number
    if (metricType === InsightType.TRENDS) {
        const controlVariant = result.variants.find((v: any) => v.key === 'control')
        const variantData = result.variants.find((v: any) => v.key === variant.key)

        if (
            !variantData?.count ||
            !variantData?.absolute_exposure ||
            !controlVariant?.count ||
            !controlVariant?.absolute_exposure
        ) {
            delta = 0
        } else {
            const controlMean = controlVariant.count / controlVariant.absolute_exposure
            const variantMean = variantData.count / variantData.absolute_exposure
            delta = (variantMean - controlMean) / controlMean
        }
    } else {
        const variantRate = conversionRateForVariant(result, variant.key)
        const controlRate = conversionRateForVariant(result, 'control')
        delta = variantRate && controlRate ? (variantRate - controlRate) / controlRate : 0
    }

    // Calculate positioning
    const y = barPadding + (barHeight + barPadding) * index
    const x1 = valueToX(lower)
    const x2 = valueToX(upper)
    const deltaX = valueToX(delta)

    return (
        <g
            key={variant.key}
            onMouseEnter={(e) => {
                const rect = e.currentTarget.getBoundingClientRect()
                setTooltipData({
                    x: rect.left + rect.width / 2,
                    y: rect.top - 10,
                    variant: variant.key,
                })
            }}
            onMouseLeave={() => setTooltipData(null)}
            onClick={() => {
                if (featureFlags[FEATURE_FLAGS.EXPERIMENT_INTERVAL_TIMESERIES]) {
                    openVariantDeltaTimeseriesModal()
                }
            }}
            className={featureFlags[FEATURE_FLAGS.EXPERIMENT_INTERVAL_TIMESERIES] ? 'cursor-pointer' : ''}
        >
            {/* Add variant name using VariantTag */}
            <foreignObject
                x={x1 - 8} // Keep same positioning as the text element
                y={y + barHeight / 2 - 10}
                width="90"
                height="16"
                transform="translate(-90, 0)" // Move left to accommodate tag width
            >
                <VariantTag
                    className="justify-end mt-0.5"
                    experimentId={experimentId as ExperimentIdType}
                    variantKey={variant.key}
                    fontSize={10}
                    muted
                />
            </foreignObject>

            {/* Violin plot */}
            {variant.key === 'control' ? (
                <path
                    d={generateViolinPath(x1, x2, y, barHeight, deltaX)}
                    fill={colors.BAR_CONTROL}
                    stroke={colors.BOUNDARY_LINES}
                    strokeWidth={1}
                    strokeDasharray="2,2"
                />
            ) : (
                <>
                    <defs>
                        <linearGradient
                            id={`gradient-${metricIndex}-${variant.key}-${isSecondary ? 'secondary' : 'primary'}`}
                            x1="0"
                            x2="1"
                            y1="0"
                            y2="0"
                        >
                            {lower < 0 && upper > 0 ? (
                                <>
                                    <stop offset="0%" stopColor={colors.BAR_NEGATIVE} />
                                    <stop
                                        offset={`${(-lower / (upper - lower)) * 100}%`}
                                        stopColor={colors.BAR_NEGATIVE}
                                    />
                                    <stop
                                        offset={`${(-lower / (upper - lower)) * 100}%`}
                                        stopColor={colors.BAR_POSITIVE}
                                    />
                                    <stop offset="100%" stopColor={colors.BAR_POSITIVE} />
                                </>
                            ) : (
                                <stop
                                    offset="100%"
                                    stopColor={upper <= 0 ? colors.BAR_NEGATIVE : colors.BAR_POSITIVE}
                                />
                            )}
                        </linearGradient>
                    </defs>
                    <path
                        d={generateViolinPath(x1, x2, y, barHeight, deltaX)}
                        fill={`url(#gradient-${metricIndex}-${variant.key}-${isSecondary ? 'secondary' : 'primary'})`}
                    />
                </>
            )}

            {/* Delta marker */}
            <g transform={`translate(${deltaX}, 0)`}>
                <line
                    x1={0}
                    y1={y}
                    x2={0}
                    y2={y + barHeight}
                    stroke={variant.key === 'control' ? colors.BAR_MIDDLE_POINT_CONTROL : colors.BAR_MIDDLE_POINT}
                    strokeWidth={2}
                    vectorEffect="non-scaling-stroke"
                    shapeRendering="crispEdges"
                />
            </g>
        </g>
    )
}

// Chart SVG component
function ChartSVG({ chartSvgRef }: { chartSvgRef: React.RefObject<SVGSVGElement> }): JSX.Element {
    const { dimensions, tickValues, valueToX, variants } = useDeltaChartContext()
    const { viewBoxWidth, chartHeight } = dimensions

    return (
        <div className="flex justify-center">
            <svg
                ref={chartSvgRef}
                viewBox={`0 0 ${viewBoxWidth} ${chartHeight}`}
                preserveAspectRatio="xMidYMid meet"
                className="ml-12 max-w-[1000px]"
                // eslint-disable-next-line react/forbid-dom-props
                style={{ minHeight: `${chartHeight}px` }} // Dynamic height based on variant count
            >
                {/* Vertical grid lines */}
                <GridLines tickValues={tickValues} valueToX={valueToX} height={chartHeight} />

                {/* Render variant bars */}
                {variants.map((variant, index) => (
                    <VariantBar key={variant.key} variant={variant} index={index} />
                ))}
            </svg>
        </div>
    )
}

// Chart controls component
function ChartControls(): JSX.Element {
    const { metricIndex, isSecondary, primaryMetricsLengthWithSharedMetrics, setIsModalOpen } = useDeltaChartContext()

    return (
        <>
            {/* Chart is z-index 100, so we need to be above it */}
            <div className="absolute top-2 left-2 z-[102]">
                <SignificanceHighlight metricIndex={metricIndex} isSecondary={isSecondary} />
            </div>
            {(isSecondary || (!isSecondary && primaryMetricsLengthWithSharedMetrics > 1)) && (
                <div
                    className="absolute bottom-2 left-2 flex justify-center bg-[var(--bg-table)] z-[101]"
                    // Chart is z-index 100, so we need to be above it
                >
                    <LemonButton
                        type="secondary"
                        size="xsmall"
                        icon={<IconGraph />}
                        onClick={() => setIsModalOpen(true)}
                    >
                        Details
                    </LemonButton>
                </div>
            )}
        </>
    )
}

// Tooltips component
function ChartTooltips(): JSX.Element {
    const {
        tooltip: { tooltipData },
        experimentId,
        result,
        metricType,
        conversionRateForVariant,
        countDataForVariant,
        exposureCountDataForVariant,
        credibleIntervalForVariant,
    } = useDeltaChartContext()

    return (
        <>
            {/* Variant result tooltip */}
            {tooltipData && (
                <VariantTooltip
                    tooltipData={tooltipData}
                    experimentId={experimentId as ExperimentIdType}
                    result={result}
                    metricType={metricType}
                    conversionRateForVariant={conversionRateForVariant}
                    countDataForVariant={countDataForVariant}
                    exposureCountDataForVariant={exposureCountDataForVariant}
                    credibleIntervalForVariant={credibleIntervalForVariant}
                />
            )}
        </>
    )
}

// Main chart content component
function DeltaChartContent({ chartSvgRef }: { chartSvgRef: React.RefObject<SVGSVGElement> }): JSX.Element {
    const { result, metric, hasMinimumExposureForResults, resultsLoading, experiment, error, dimensions } =
        useDeltaChartContext()

    const { chartHeight } = dimensions

    if (result && hasMinimumExposureForResults) {
        return (
            <div className="relative w-full max-w-screen">
                <ChartControls />
                <ChartSVG chartSvgRef={chartSvgRef} />
                <ChartTooltips />
            </div>
        )
    } else if (resultsLoading) {
        return <ChartLoadingState height={chartHeight} />
    }

    return (
        <div className="relative w-full max-w-screen">
            <ChartEmptyState
                height={chartHeight}
                experimentStarted={!!experiment.start_date}
                hasMinimumExposure={hasMinimumExposureForResults}
                metric={metric}
                error={error}
            />
        </div>
    )
}

// Main DeltaChart component
export function DeltaChart({
    isSecondary,
    result,
    error,
    variants,
    metricType,
    metricIndex,
    isFirstMetric,
    metric,
    tickValues,
    chartBound,
}: {
    isSecondary: boolean
    result: any
    error: any
    variants: any[]
    metricType: InsightType
    metricIndex: number
    isFirstMetric: boolean
    metric: any
    tickValues: number[]
    chartBound: number
}): JSX.Element {
    // Get values from logic
    const {
        credibleIntervalForVariant,
        conversionRateForVariant,
        experimentId,
        experiment,
        countDataForVariant,
        exposureCountDataForVariant,
        metricResultsLoading,
        secondaryMetricResultsLoading,
        featureFlags,
        primaryMetricsLengthWithSharedMetrics,
        hasMinimumExposureForResults,
    } = useValues(experimentLogic)

    const { openVariantDeltaTimeseriesModal } = useActions(experimentLogic)

    // Loading state
    const resultsLoading = isSecondary ? secondaryMetricResultsLoading : metricResultsLoading

    // Chart dimensions
    const dimensions = useChartDimensions(variants)
    const { viewBoxWidth: VIEW_BOX_WIDTH, horizontalPadding: HORIZONTAL_PADDING } = dimensions

    // Colors
    const colors = useChartColors()

    // Modal state
    const [isModalOpen, setIsModalOpen] = useState(false)

    // Tooltip state
    const [tooltipData, setTooltipData] = useState<{ x: number; y: number; variant: string } | null>(null)
    const [emptyStateTooltipVisible, setEmptyStateTooltipVisible] = useState(false)
    const [tooltipPosition, setTooltipPosition] = useState({ x: 0, y: 0 })

    // Value to X coordinate function
    const valueToX = (value: number): number => {
        // Scale the value to fit within the padded area
        const percentage = (value / chartBound + 1) / 2
        return HORIZONTAL_PADDING + percentage * (VIEW_BOX_WIDTH - 2 * HORIZONTAL_PADDING)
    }

    // Metric title panel
    const metricTitlePanel = (
        <MetricHeader
            metricIndex={metricIndex}
            metric={metric}
            metricType={metricType}
            isPrimaryMetric={!isSecondary}
        />
    )

    // Chart content function that receives the ref from layout
    const chartContent = (chartSvgRef: React.RefObject<SVGSVGElement>): JSX.Element => (
        <DeltaChartContent chartSvgRef={chartSvgRef} />
    )

    // Create context value
    const contextValue: DeltaChartContextType = {
        // Chart properties
        result,
        error,
        metricIndex,
        isSecondary,
        metricType,
        metric,
        tickValues,
        chartBound,

        // Experiment data
        experimentId: experimentId as ExperimentIdType, // Cast to ensure type compatibility
        experiment,
        variants,
        hasMinimumExposureForResults,
        featureFlags,
        primaryMetricsLengthWithSharedMetrics,

        // Data transformation functions
        valueToX,
        credibleIntervalForVariant,
        conversionRateForVariant,
        countDataForVariant,
        exposureCountDataForVariant,

        // Chart dimensions
        dimensions,

        // UI state & actions
        isModalOpen,
        setIsModalOpen,
        resultsLoading,
        openVariantDeltaTimeseriesModal,

        // Colors
        colors,

        // Tooltip state
        tooltip: {
            tooltipData,
            setTooltipData,
            emptyStateTooltipVisible,
            setEmptyStateTooltipVisible,
            tooltipPosition,
            setTooltipPosition,
        },
    }

    return (
        <DeltaChartContext.Provider value={contextValue}>
            <MetricsChartLayout
                isFirstMetric={isFirstMetric}
                tickValues={tickValues}
                chartBound={chartBound}
                metricTitlePanel={metricTitlePanel}
                chartContent={chartContent}
                viewBoxWidth={VIEW_BOX_WIDTH}
                horizontalPadding={HORIZONTAL_PADDING}
            />

            {/* Modal for metric details */}
            <ChartModal
                isOpen={isModalOpen}
                onClose={() => setIsModalOpen(false)}
                metric={metric}
                metricIndex={metricIndex}
                isSecondary={isSecondary}
                result={result}
                experimentId={experimentId as ExperimentIdType}
            />
        </DeltaChartContext.Provider>
    )
}
