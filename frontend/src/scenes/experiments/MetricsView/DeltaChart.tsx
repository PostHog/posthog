import { IconGraph } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { FEATURE_FLAGS } from 'lib/constants'
import { useEffect, useRef, useState } from 'react'

import { InsightType } from '~/types'

import { experimentLogic } from '../experimentLogic'
import { VariantTag } from '../ExperimentView/components'
import { ChartEmptyState } from './ChartEmptyState'
import { ChartLoadingState } from './ChartLoadingState'
import { ChartModal } from './ChartModal'
import { useChartColors } from './colors'
import { EmptyStateTooltip } from './EmptyStateTooltip'
import { GridLines } from './GridLines'
import { MetricHeader } from './MetricHeader'
import { SignificanceHighlight } from './SignificanceHighlight'
import { VariantTooltip } from './VariantTooltip'
import { generateViolinPath } from './violinUtils'

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

    const [tooltipData, setTooltipData] = useState<{ x: number; y: number; variant: string } | null>(null)
    const [emptyStateTooltipVisible, setEmptyStateTooltipVisible] = useState(true)
    const [tooltipPosition] = useState({ x: 0, y: 0 })
    const [isModalOpen, setIsModalOpen] = useState(false)

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

    const resultsLoading = isSecondary ? secondaryMetricResultsLoading : metricResultsLoading

    const BAR_HEIGHT = 10 + getScaleAddition(variants.length)
    const BAR_PADDING = 10 + getScaleAddition(variants.length)
    const TICK_PANEL_HEIGHT = 20
    const VIEW_BOX_WIDTH = 800
    const HORIZONTAL_PADDING = 20
    // Width defined in utility classes: max-w-[1000px]

    const colors = useChartColors()

    // Update chart height calculation to include only one BAR_PADDING for each space between bars
    const chartHeight = BAR_PADDING + (BAR_HEIGHT + BAR_PADDING) * variants.length

    const valueToX = (value: number): number => {
        // Scale the value to fit within the padded area
        const percentage = (value / chartBound + 1) / 2
        return HORIZONTAL_PADDING + percentage * (VIEW_BOX_WIDTH - 2 * HORIZONTAL_PADDING)
    }

    // Panel width defined in utility classes: w-1/5

    const ticksSvgRef = useRef<SVGSVGElement>(null)
    const chartSvgRef = useRef<SVGSVGElement>(null)
    // :TRICKY: We need to track SVG heights dynamically because
    // we're fitting regular divs to match SVG viewports. SVGs scale
    // based on their viewBox and the viewport size, making it challenging
    // to match their effective rendered heights with regular div elements.
    // Use underscore prefix to indicate these state variables are used indirectly
    const [, setTicksSvgHeight] = useState<number>(0)
    const [, setChartSvgHeight] = useState<number>(0)

    useEffect(() => {
        const ticksSvg = ticksSvgRef.current
        const chartSvg = chartSvgRef.current

        // eslint-disable-next-line compat/compat
        const resizeObserver = new ResizeObserver((entries) => {
            for (const entry of entries) {
                if (entry.target === ticksSvg) {
                    setTicksSvgHeight(entry.contentRect.height)
                } else if (entry.target === chartSvg) {
                    setChartSvgHeight(entry.contentRect.height)
                }
            }
        })

        if (ticksSvg) {
            resizeObserver.observe(ticksSvg)
        }
        if (chartSvg) {
            resizeObserver.observe(chartSvg)
        }

        return () => {
            resizeObserver.disconnect()
        }
    }, [result])

    return (
        <div className="rounded bg-[var(--bg-table)]">
            {/* Metric title panel */}
            <div className="inline-align-top w-1/5">
                {isFirstMetric && <svg className="h-full" />}
                {isFirstMetric && <div className="w-full border-t border-primary" />}
                <div
                    className="p-2 border-r h-full"
                    // eslint-disable-next-line react/forbid-dom-props
                    style={{ borderColor: colors.BOUNDARY_LINES }} // Dynamic color from theme
                >
                    <MetricHeader
                        metricIndex={metricIndex}
                        metric={metric}
                        metricType={metricType}
                        isPrimaryMetric={!isSecondary}
                    />
                </div>
            </div>
            {/* SVGs container */}
            <div className="inline-align-top min-w-[780px] w-4/5">
                {/* Ticks */}
                {isFirstMetric && (
                    <div className="flex justify-center">
                        <svg
                            ref={ticksSvgRef}
                            viewBox={`0 0 ${VIEW_BOX_WIDTH} ${TICK_PANEL_HEIGHT}`}
                            preserveAspectRatio="xMidYMid meet"
                            className={`${result ? 'ml-12' : ''} min-h-[20px] max-w-[1000px]`}
                        >
                            {tickValues.map((value, index) => {
                                const x = valueToX(value)
                                return (
                                    <g key={index}>
                                        <text
                                            x={x}
                                            y={TICK_PANEL_HEIGHT / 2}
                                            textAnchor="middle"
                                            dominantBaseline="middle"
                                            fontSize={9}
                                            fill={colors.TICK_TEXT_COLOR}
                                            fontWeight="600"
                                        >
                                            {value === 0 ? '0%' : `${(value * 100).toFixed(value < 0.1 ? 1 : 0)}%`}
                                        </text>
                                    </g>
                                )
                            })}
                        </svg>
                    </div>
                )}
                {isFirstMetric && <div className="w-full border-t border-primary" />}

                {/* Chart */}
                {result && hasMinimumExposureForResults ? (
                    <div className="relative">
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
                        <div className="flex justify-center">
                            <svg
                                ref={chartSvgRef}
                                viewBox={`0 0 ${VIEW_BOX_WIDTH} ${chartHeight}`}
                                preserveAspectRatio="xMidYMid meet"
                                className="ml-12 max-w-[1000px]"
                                // eslint-disable-next-line react/forbid-dom-props
                                style={{ minHeight: `${chartHeight}px` }} // Dynamic height based on variant count
                            >
                                {/* Vertical grid lines */}
                                <GridLines tickValues={tickValues} valueToX={valueToX} height={chartHeight} />

                                {variants.map((variant, index) => {
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
                                        delta =
                                            variantRate && controlRate ? (variantRate - controlRate) / controlRate : 0
                                    }

                                    const y = BAR_PADDING + (BAR_HEIGHT + BAR_PADDING) * index
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
                                            className={
                                                featureFlags[FEATURE_FLAGS.EXPERIMENT_INTERVAL_TIMESERIES]
                                                    ? 'cursor-pointer'
                                                    : ''
                                            }
                                        >
                                            {/* Add variant name using VariantTag */}
                                            <foreignObject
                                                x={x1 - 8} // Keep same positioning as the text element
                                                y={y + BAR_HEIGHT / 2 - 10}
                                                width="90"
                                                height="16"
                                                transform="translate(-90, 0)" // Move left to accommodate tag width
                                            >
                                                <VariantTag
                                                    className="justify-end mt-0.5"
                                                    experimentId={experimentId}
                                                    variantKey={variant.key}
                                                    fontSize={10}
                                                    muted
                                                />
                                            </foreignObject>

                                            {/* Violin plot */}
                                            {variant.key === 'control' ? (
                                                <path
                                                    d={generateViolinPath(x1, x2, y, BAR_HEIGHT, deltaX)}
                                                    fill={colors.BAR_CONTROL}
                                                    stroke={colors.BOUNDARY_LINES}
                                                    strokeWidth={1}
                                                    strokeDasharray="2,2"
                                                />
                                            ) : (
                                                <>
                                                    <defs>
                                                        <linearGradient
                                                            id={`gradient-${metricIndex}-${variant.key}-${
                                                                isSecondary ? 'secondary' : 'primary'
                                                            }`}
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
                                                                    <stop
                                                                        offset="100%"
                                                                        stopColor={colors.BAR_POSITIVE}
                                                                    />
                                                                </>
                                                            ) : (
                                                                <stop
                                                                    offset="100%"
                                                                    stopColor={
                                                                        upper <= 0
                                                                            ? colors.BAR_NEGATIVE
                                                                            : colors.BAR_POSITIVE
                                                                    }
                                                                />
                                                            )}
                                                        </linearGradient>
                                                    </defs>
                                                    <path
                                                        d={generateViolinPath(x1, x2, y, BAR_HEIGHT, deltaX)}
                                                        fill={`url(#gradient-${metricIndex}-${variant.key}-${
                                                            isSecondary ? 'secondary' : 'primary'
                                                        })`}
                                                    />
                                                </>
                                            )}

                                            {/* Delta marker */}
                                            <g transform={`translate(${deltaX}, 0)`}>
                                                <line
                                                    x1={0}
                                                    y1={y}
                                                    x2={0}
                                                    y2={y + BAR_HEIGHT}
                                                    stroke={
                                                        variant.key === 'control'
                                                            ? colors.BAR_MIDDLE_POINT_CONTROL
                                                            : colors.BAR_MIDDLE_POINT
                                                    }
                                                    strokeWidth={2}
                                                    vectorEffect="non-scaling-stroke"
                                                    shapeRendering="crispEdges"
                                                />
                                            </g>
                                        </g>
                                    )
                                })}
                            </svg>
                        </div>
                    </div>
                ) : resultsLoading ? (
                    <ChartLoadingState width={VIEW_BOX_WIDTH} height={chartHeight} />
                ) : (
                    <ChartEmptyState
                        width={VIEW_BOX_WIDTH}
                        height={chartHeight}
                        experimentStarted={!!experiment.start_date}
                        hasMinimumExposure={hasMinimumExposureForResults}
                        error={error}
                    />
                )}

                {/* Variant result tooltip */}
                {tooltipData && (
                    <VariantTooltip
                        tooltipData={tooltipData}
                        experimentId={experimentId}
                        result={result}
                        metricType={metricType}
                        conversionRateForVariant={conversionRateForVariant}
                        countDataForVariant={countDataForVariant}
                        exposureCountDataForVariant={exposureCountDataForVariant}
                        credibleIntervalForVariant={credibleIntervalForVariant}
                    />
                )}

                {/* Empty state tooltip */}
                {emptyStateTooltipVisible && error && (
                    <EmptyStateTooltip
                        tooltipPosition={tooltipPosition}
                        error={error}
                        metric={metric}
                        setEmptyStateTooltipVisible={setEmptyStateTooltipVisible}
                    />
                )}
            </div>

            {/* Modal for metric details */}
            <ChartModal
                isOpen={isModalOpen}
                onClose={() => setIsModalOpen(false)}
                metric={metric}
                metricIndex={metricIndex}
                isSecondary={isSecondary}
                result={result}
                experimentId={experimentId}
            />
        </div>
    )
}
