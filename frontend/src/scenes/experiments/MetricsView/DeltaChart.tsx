import { IconActivity, IconClock, IconGraph, IconMinus, IconTrending } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonModal, LemonTag, LemonTagType, Tooltip } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonProgress } from 'lib/lemon-ui/LemonProgress'
import { humanFriendlyNumber } from 'lib/utils'
import { useEffect, useRef, useState } from 'react'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'
import { NodeKind } from '~/queries/schema/schema-general'
import { InsightType, TrendExperimentVariant } from '~/types'

import { EXPERIMENT_MIN_EXPOSURES_FOR_RESULTS } from '../constants'
import { experimentLogic } from '../experimentLogic'
import { ExploreButton, ResultsQuery, VariantTag } from '../ExperimentView/components'
import { SignificanceText, WinningVariantText } from '../ExperimentView/Overview'
import { SummaryTable } from '../ExperimentView/SummaryTable'
import { MetricHeader } from './MetricHeader'
import { NoResultEmptyState } from './NoResultEmptyState'

function formatTickValue(value: number): string {
    if (value === 0) {
        return '0%'
    }

    // Determine number of decimal places needed
    const absValue = Math.abs(value)
    let decimals = 0

    if (absValue < 0.01) {
        decimals = 3
    } else if (absValue < 0.1) {
        decimals = 2
    } else if (absValue < 1) {
        decimals = 1
    } else {
        decimals = 0
    }

    return `${(value * 100).toFixed(decimals)}%`
}

export function generateViolinPath(x1: number, x2: number, y: number, height: number, deltaX: number): string {
    // Create points for the violin curve
    const points: [number, number][] = []
    const steps = 20
    const maxWidth = height / 2

    // Generate left side points (x1 to deltaX)
    for (let i = 0; i <= steps; i++) {
        const t = i / steps
        const x = x1 + (deltaX - x1) * t
        // Standard normal distribution PDF from x1 to deltaX
        const z = (t - 1) * 2 // Reduced scale factor from 2.5 to 2 for thicker tails
        const width = Math.exp(-0.5 * z * z) * maxWidth
        points.push([x, y + height / 2 - width])
    }

    // Generate right side points (deltaX to x2)
    for (let i = 0; i <= steps; i++) {
        const t = i / steps
        const x = deltaX + (x2 - deltaX) * t
        // Standard normal distribution PDF from deltaX to x2
        const z = t * 2 // Reduced scale factor from 2.5 to 2 for thicker tails
        const width = Math.exp(-0.5 * z * z) * maxWidth
        points.push([x, y + height / 2 - width])
    }

    // Generate bottom curve points (mirror of top)
    for (let i = steps; i >= 0; i--) {
        const t = i / steps
        const x = deltaX + (x2 - deltaX) * t
        const z = t * 2
        const width = Math.exp(-0.5 * z * z) * maxWidth
        points.push([x, y + height / 2 + width])
    }
    for (let i = steps; i >= 0; i--) {
        const t = i / steps
        const x = x1 + (deltaX - x1) * t
        const z = (t - 1) * 2
        const width = Math.exp(-0.5 * z * z) * maxWidth
        points.push([x, y + height / 2 + width])
    }

    // Create SVG path
    return `
        M ${points[0][0]} ${points[0][1]}
        ${points.map((point) => `L ${point[0]} ${point[1]}`).join(' ')}
        Z
    `
}

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

    const {
        // openPrimaryMetricModal,
        // openSecondaryMetricModal,
        // openPrimarySharedMetricModal,
        // openSecondarySharedMetricModal,
        openVariantDeltaTimeseriesModal,
    } = useActions(experimentLogic)

    const [tooltipData, setTooltipData] = useState<{ x: number; y: number; variant: string } | null>(null)
    const [emptyStateTooltipVisible, setEmptyStateTooltipVisible] = useState(true)
    const [tooltipPosition, setTooltipPosition] = useState({ x: 0, y: 0 })
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
    const CONVERSION_RATE_RECT_WIDTH = 2
    const TICK_FONT_SIZE = 9
    const CHART_MAX_WIDTH = 1000

    const { isDarkModeOn } = useValues(themeLogic)
    const COLORS = {
        TICK_TEXT_COLOR: 'var(--text-tertiary)',
        BOUNDARY_LINES: 'var(--border-primary)',
        ZERO_LINE: 'var(--border-bold)',
        BAR_NEGATIVE: isDarkModeOn ? '#c32f45' : '#f84257',
        BAR_POSITIVE: isDarkModeOn ? '#12a461' : '#36cd6f',
        BAR_DEFAULT: isDarkModeOn ? 'rgb(121 121 121)' : 'rgb(217 217 217)',
        BAR_CONTROL: isDarkModeOn ? 'rgba(217, 217, 217, 0.2)' : 'rgba(217, 217, 217, 0.4)',
        BAR_MIDDLE_POINT: 'black',
        BAR_MIDDLE_POINT_CONTROL: 'rgba(0, 0, 0, 0.4)',
    }

    // Update chart height calculation to include only one BAR_PADDING for each space between bars
    const chartHeight = BAR_PADDING + (BAR_HEIGHT + BAR_PADDING) * variants.length

    const valueToX = (value: number): number => {
        // Scale the value to fit within the padded area
        const percentage = (value / chartBound + 1) / 2
        return HORIZONTAL_PADDING + percentage * (VIEW_BOX_WIDTH - 2 * HORIZONTAL_PADDING)
    }

    const metricTitlePanelWidth = '20%'

    const ticksSvgRef = useRef<SVGSVGElement>(null)
    const chartSvgRef = useRef<SVGSVGElement>(null)
    // :TRICKY: We need to track SVG heights dynamically because
    // we're fitting regular divs to match SVG viewports. SVGs scale
    // based on their viewBox and the viewport size, making it challenging
    // to match their effective rendered heights with regular div elements.
    const [ticksSvgHeight, setTicksSvgHeight] = useState<number>(0)
    const [chartSvgHeight, setChartSvgHeight] = useState<number>(0)

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
            {/* eslint-disable-next-line react/forbid-dom-props */}
            <div style={{ width: metricTitlePanelWidth, verticalAlign: 'top', display: 'inline-block' }}>
                {isFirstMetric && (
                    <svg
                        // eslint-disable-next-line react/forbid-dom-props
                        style={{ height: `${ticksSvgHeight}px` }}
                    />
                )}
                {isFirstMetric && <div className="w-full border-t border-primary" />}
                <div
                    // eslint-disable-next-line react/forbid-dom-props
                    style={{ height: `${chartSvgHeight}px`, borderRight: `1px solid ${COLORS.BOUNDARY_LINES}` }}
                    className="p-2"
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
            <div
                // eslint-disable-next-line react/forbid-dom-props
                style={{
                    width: `calc(100% - ${metricTitlePanelWidth})`,
                    verticalAlign: 'top',
                    display: 'inline-block',
                    minWidth: '780px',
                }}
            >
                {/* Ticks */}
                {isFirstMetric && (
                    <div className="flex justify-center">
                        <svg
                            ref={ticksSvgRef}
                            viewBox={`0 0 ${VIEW_BOX_WIDTH} ${TICK_PANEL_HEIGHT}`}
                            preserveAspectRatio="xMidYMid meet"
                            className={result ? 'ml-12' : undefined}
                            // eslint-disable-next-line react/forbid-dom-props
                            style={{ minHeight: `${TICK_PANEL_HEIGHT}px`, maxWidth: `${CHART_MAX_WIDTH}px` }}
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
                                            fontSize={TICK_FONT_SIZE}
                                            fill={COLORS.TICK_TEXT_COLOR}
                                            fontWeight="600"
                                        >
                                            {formatTickValue(value)}
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
                        {/* eslint-disable-next-line react/forbid-dom-props */}
                        <div className="absolute top-2 left-2" style={{ zIndex: 102 }}>
                            <SignificanceHighlight metricIndex={metricIndex} isSecondary={isSecondary} />
                        </div>
                        {(isSecondary || (!isSecondary && primaryMetricsLengthWithSharedMetrics > 1)) && (
                            <div
                                className="absolute bottom-2 left-2 flex justify-center bg-[var(--bg-table)]"
                                // Chart is z-index 100, so we need to be above it
                                // eslint-disable-next-line react/forbid-dom-props
                                style={{ zIndex: 101 }}
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
                                className="ml-12"
                                // eslint-disable-next-line react/forbid-dom-props
                                style={{ minHeight: `${chartHeight}px`, maxWidth: `${CHART_MAX_WIDTH}px` }}
                            >
                                {/* Vertical grid lines */}
                                {tickValues.map((value, index) => {
                                    const x = valueToX(value)
                                    return (
                                        <line
                                            key={index}
                                            x1={x}
                                            y1={0}
                                            x2={x}
                                            y2={chartSvgHeight + 20}
                                            stroke={value === 0 ? COLORS.ZERO_LINE : COLORS.BOUNDARY_LINES}
                                            strokeWidth={value === 0 ? 1 : 0.5}
                                        />
                                    )
                                })}

                                {variants.map((variant, index) => {
                                    const interval = credibleIntervalForVariant(result, variant.key, metricType)
                                    const [lower, upper] = interval ? [interval[0] / 100, interval[1] / 100] : [0, 0]

                                    let delta: number
                                    if (metricType === InsightType.TRENDS) {
                                        const controlVariant = result.variants.find(
                                            (v: TrendExperimentVariant) => v.key === 'control'
                                        ) as TrendExperimentVariant

                                        const variantData = result.variants.find(
                                            (v: TrendExperimentVariant) => v.key === variant.key
                                        ) as TrendExperimentVariant

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

                                            {variant.key === 'control' ? (
                                                // Control variant - dashed violin
                                                <path
                                                    d={generateViolinPath(x1, x2, y, BAR_HEIGHT, deltaX)}
                                                    fill={COLORS.BAR_CONTROL}
                                                    stroke={COLORS.BOUNDARY_LINES}
                                                    strokeWidth={1}
                                                    strokeDasharray="2,2"
                                                />
                                            ) : (
                                                // Test variants - single violin with gradient fill
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
                                                                    <stop offset="0%" stopColor={COLORS.BAR_NEGATIVE} />
                                                                    <stop
                                                                        offset={`${(-lower / (upper - lower)) * 100}%`}
                                                                        stopColor={COLORS.BAR_NEGATIVE}
                                                                    />
                                                                    <stop
                                                                        offset={`${(-lower / (upper - lower)) * 100}%`}
                                                                        stopColor={COLORS.BAR_POSITIVE}
                                                                    />
                                                                    <stop
                                                                        offset="100%"
                                                                        stopColor={COLORS.BAR_POSITIVE}
                                                                    />
                                                                </>
                                                            ) : (
                                                                <stop
                                                                    offset="100%"
                                                                    stopColor={
                                                                        upper <= 0
                                                                            ? COLORS.BAR_NEGATIVE
                                                                            : COLORS.BAR_POSITIVE
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
                                                            ? COLORS.BAR_MIDDLE_POINT_CONTROL
                                                            : COLORS.BAR_MIDDLE_POINT
                                                    }
                                                    strokeWidth={CONVERSION_RATE_RECT_WIDTH}
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
                    <svg
                        ref={chartSvgRef}
                        viewBox={`0 0 ${VIEW_BOX_WIDTH} ${chartHeight}`}
                        preserveAspectRatio="xMidYMid meet"
                    >
                        <foreignObject
                            x={VIEW_BOX_WIDTH / 2 - 100} // Center the 200px wide container
                            y={chartHeight / 2 - 10} // Roughly center vertically
                            width="200"
                            height="20"
                        >
                            <div
                                className="flex items-center justify-center text-secondary cursor-default"
                                // eslint-disable-next-line react/forbid-dom-props
                                style={{ fontSize: '10px', fontWeight: 400 }}
                            >
                                <span>Results loading&hellip;</span>
                            </div>
                        </foreignObject>
                    </svg>
                ) : (
                    <svg
                        ref={chartSvgRef}
                        viewBox={`0 0 ${VIEW_BOX_WIDTH} ${chartHeight}`}
                        preserveAspectRatio="xMidYMid meet"
                    >
                        {!experiment.start_date ? (
                            <foreignObject x="0" y={chartHeight / 2 - 10} width={VIEW_BOX_WIDTH} height="20">
                                <div
                                    className="flex items-center ml-2 xl:ml-0 xl:justify-center text-secondary cursor-default"
                                    // eslint-disable-next-line react/forbid-dom-props
                                    style={{ fontSize: '10px', fontWeight: 400 }}
                                >
                                    <LemonTag size="small" className="mr-2">
                                        <IconClock fontSize="1em" />
                                    </LemonTag>
                                    <span>Waiting for experiment to start&hellip;</span>
                                </div>
                            </foreignObject>
                        ) : !hasMinimumExposureForResults ? (
                            <foreignObject x="0" y={chartHeight / 2 - 10} width={VIEW_BOX_WIDTH} height="20">
                                <div
                                    className="flex items-center ml-2 xl:ml-0 xl:justify-center text-secondary cursor-default"
                                    // eslint-disable-next-line react/forbid-dom-props
                                    style={{ fontSize: '10px', fontWeight: 400 }}
                                >
                                    <LemonTag size="small" className="mr-2">
                                        <IconActivity fontSize="1em" />
                                    </LemonTag>
                                    <span>
                                        Waiting for {EXPERIMENT_MIN_EXPOSURES_FOR_RESULTS}+ exposures per variant to
                                        show results
                                    </span>
                                </div>
                            </foreignObject>
                        ) : (
                            <foreignObject
                                x={0}
                                y={chartHeight / 2 - 10}
                                width={VIEW_BOX_WIDTH}
                                height="20"
                                onMouseEnter={(e) => {
                                    const rect = e.currentTarget.getBoundingClientRect()
                                    setTooltipPosition({
                                        x: rect.left + rect.width / 2,
                                        y: rect.top,
                                    })
                                    setEmptyStateTooltipVisible(true)
                                }}
                                onMouseLeave={() => setEmptyStateTooltipVisible(false)}
                            >
                                <div
                                    className="flex items-center ml-2 xl:ml-0 xl:justify-center text-secondary cursor-default"
                                    // eslint-disable-next-line react/forbid-dom-props
                                    style={{ fontSize: '10px', fontWeight: 400 }}
                                >
                                    {error?.hasDiagnostics ? (
                                        <LemonTag size="small" type="highlight" className="mr-2">
                                            <IconActivity className="mr-1" fontSize="1em" />
                                            <span className="font-semibold">
                                                {(() => {
                                                    try {
                                                        return Object.values(error.detail).filter((v) => v === false)
                                                            .length
                                                    } catch {
                                                        return '0'
                                                    }
                                                })()}
                                            </span>
                                            /
                                            <span className="font-semibold">
                                                {metricType === InsightType.TRENDS ? '3' : '2'}
                                            </span>
                                        </LemonTag>
                                    ) : (
                                        <LemonTag size="small" type="danger" className="mr-1">
                                            Error
                                        </LemonTag>
                                    )}
                                    <span>Results not yet available</span>
                                </div>
                            </foreignObject>
                        )}
                    </svg>
                )}

                {/* Variant result tooltip */}
                {tooltipData && (
                    <div
                        // eslint-disable-next-line react/forbid-dom-props
                        style={{
                            position: 'fixed',
                            left: tooltipData.x,
                            top: tooltipData.y,
                            transform: 'translate(-50%, -100%)',
                            backgroundColor: 'var(--bg-surface-primary)',
                            border: '1px solid var(--border-primary)',
                            padding: '8px 12px',
                            borderRadius: '6px',
                            fontSize: '13px',
                            boxShadow: '0 4px 12px rgba(0, 0, 0, 0.1)',
                            pointerEvents: 'none',
                            zIndex: 100,
                            minWidth: '300px',
                        }}
                    >
                        <div className="flex flex-col gap-1">
                            <VariantTag experimentId={experimentId} variantKey={tooltipData.variant} />
                            <div className="inline-flex">
                                <span className="text-secondary font-semibold mb-1">Win probability:</span>
                                {result?.probability?.[tooltipData.variant] !== undefined ? (
                                    <span className="flex items-center justify-between flex-1 pl-6">
                                        <LemonProgress
                                            className="w-3/4 mr-4"
                                            percent={result.probability[tooltipData.variant] * 100}
                                        />
                                        <span className="font-semibold">
                                            {(result.probability[tooltipData.variant] * 100).toFixed(2)}%
                                        </span>
                                    </span>
                                ) : (
                                    '—'
                                )}
                            </div>
                            {metricType === InsightType.TRENDS ? (
                                <>
                                    <div className="flex justify-between items-center">
                                        <span className="text-secondary font-semibold">
                                            {metricType === InsightType.TRENDS &&
                                            result.exposure_query?.series?.[0]?.math
                                                ? 'Total'
                                                : 'Count'}
                                            :
                                        </span>
                                        <span className="font-semibold">
                                            {(() => {
                                                const count = countDataForVariant(result, tooltipData.variant)
                                                return count !== null ? humanFriendlyNumber(count) : '—'
                                            })()}
                                        </span>
                                    </div>
                                    <div className="flex justify-between items-center">
                                        <span className="text-secondary font-semibold">Exposure:</span>
                                        <span className="font-semibold">
                                            {(() => {
                                                const exposure = exposureCountDataForVariant(
                                                    result,
                                                    tooltipData.variant
                                                )
                                                return exposure !== null ? humanFriendlyNumber(exposure) : '—'
                                            })()}
                                        </span>
                                    </div>
                                    <div className="flex justify-between items-center">
                                        <span className="text-secondary font-semibold">Mean:</span>
                                        <span className="font-semibold">
                                            {(() => {
                                                const variant = result.variants.find(
                                                    (v: TrendExperimentVariant) => v.key === tooltipData.variant
                                                )
                                                return variant?.count && variant?.absolute_exposure
                                                    ? (variant.count / variant.absolute_exposure).toFixed(2)
                                                    : '—'
                                            })()}
                                        </span>
                                    </div>
                                </>
                            ) : (
                                <div className="flex justify-between items-center">
                                    <span className="text-secondary font-semibold">Conversion rate:</span>
                                    <span className="font-semibold">
                                        {conversionRateForVariant(result, tooltipData.variant)?.toFixed(2)}%
                                    </span>
                                </div>
                            )}
                            <div className="flex justify-between items-center">
                                <span className="text-secondary font-semibold">Delta:</span>
                                <span className="font-semibold">
                                    {tooltipData.variant === 'control' ? (
                                        <em className="text-secondary">Baseline</em>
                                    ) : (
                                        (() => {
                                            if (metricType === InsightType.TRENDS) {
                                                const controlVariant = result.variants.find(
                                                    (v: TrendExperimentVariant) => v.key === 'control'
                                                )
                                                const variant = result.variants.find(
                                                    (v: TrendExperimentVariant) => v.key === tooltipData.variant
                                                )

                                                if (
                                                    !variant?.count ||
                                                    !variant?.absolute_exposure ||
                                                    !controlVariant?.count ||
                                                    !controlVariant?.absolute_exposure
                                                ) {
                                                    return '—'
                                                }

                                                const controlMean =
                                                    controlVariant.count / controlVariant.absolute_exposure
                                                const variantMean = variant.count / variant.absolute_exposure
                                                const delta = (variantMean - controlMean) / controlMean
                                                return delta ? (
                                                    <span className={delta > 0 ? 'text-success' : 'text-danger'}>
                                                        {`${delta > 0 ? '+' : ''}${(delta * 100).toFixed(2)}%`}
                                                    </span>
                                                ) : (
                                                    '—'
                                                )
                                            }

                                            const variantRate = conversionRateForVariant(result, tooltipData.variant)
                                            const controlRate = conversionRateForVariant(result, 'control')
                                            const delta =
                                                variantRate && controlRate
                                                    ? (variantRate - controlRate) / controlRate
                                                    : 0
                                            return delta ? (
                                                <span className={delta > 0 ? 'text-success' : 'text-danger'}>
                                                    {`${delta > 0 ? '+' : ''}${(delta * 100).toFixed(2)}%`}
                                                </span>
                                            ) : (
                                                '—'
                                            )
                                        })()
                                    )}
                                </span>
                            </div>
                            <div className="flex justify-between items-center">
                                <span className="text-secondary font-semibold">Credible interval:</span>
                                <span className="font-semibold">
                                    {(() => {
                                        const interval = credibleIntervalForVariant(
                                            result,
                                            tooltipData.variant,
                                            metricType
                                        )
                                        const [lower, upper] = interval
                                            ? [interval[0] / 100, interval[1] / 100]
                                            : [0, 0]
                                        return `[${lower > 0 ? '+' : ''}${(lower * 100).toFixed(2)}%, ${
                                            upper > 0 ? '+' : ''
                                        }${(upper * 100).toFixed(2)}%]`
                                    })()}
                                </span>
                            </div>
                        </div>
                    </div>
                )}

                {/* Empty state tooltip */}
                {emptyStateTooltipVisible && (
                    <div
                        // eslint-disable-next-line react/forbid-dom-props
                        style={{
                            position: 'fixed',
                            left: tooltipPosition.x,
                            top: tooltipPosition.y,
                            transform: 'translate(-50%, -100%)',
                            backgroundColor: 'var(--bg-surface-primary)',
                            border: '1px solid var(--border-primary)',
                            padding: '8px 12px',
                            borderRadius: '6px',
                            fontSize: '13px',
                            boxShadow: '0 4px 12px rgba(0, 0, 0, 0.1)',
                            zIndex: 100,
                            minWidth: '200px',
                        }}
                        onMouseEnter={() => setEmptyStateTooltipVisible(true)}
                        onMouseLeave={() => setEmptyStateTooltipVisible(false)}
                    >
                        <NoResultEmptyState error={error} metric={metric} />
                    </div>
                )}
            </div>

            <LemonModal
                isOpen={isModalOpen}
                onClose={() => setIsModalOpen(false)}
                width={1200}
                title={`Metric results: ${metric.name || 'Untitled metric'}`}
                footer={
                    <LemonButton
                        form="secondary-metric-modal-form"
                        type="secondary"
                        onClick={() => setIsModalOpen(false)}
                    >
                        Close
                    </LemonButton>
                }
            >
                {/* TODO: Only show explore button if the metric is a trends or funnels query. Not supported yet with new query runner */}
                {result &&
                    (result.kind === NodeKind.ExperimentTrendsQuery ||
                        result.kind === NodeKind.ExperimentFunnelsQuery) && (
                        <div className="flex justify-end">
                            <ExploreButton result={result} />
                        </div>
                    )}
                <LemonBanner type={result?.significant ? 'success' : 'info'} className="mb-4">
                    <div className="items-center inline-flex flex-wrap">
                        <WinningVariantText result={result} experimentId={experimentId} />
                        <SignificanceText metricIndex={metricIndex} />
                    </div>
                </LemonBanner>
                <SummaryTable metric={metric} metricIndex={metricIndex} isSecondary={isSecondary} />
                {/* TODO: Only show results query if the metric is a trends or funnels query. Not supported yet with new query runner */}
                {result &&
                    (result.kind === NodeKind.ExperimentTrendsQuery ||
                        result.kind === NodeKind.ExperimentFunnelsQuery) && (
                        <ResultsQuery result={result} showTable={true} />
                    )}
            </LemonModal>
        </div>
    )
}

function SignificanceHighlight({
    metricIndex = 0,
    isSecondary = false,
    className = '',
}: {
    metricIndex?: number
    isSecondary?: boolean
    className?: string
}): JSX.Element {
    const { isPrimaryMetricSignificant, isSecondaryMetricSignificant, significanceDetails } = useValues(experimentLogic)
    const isSignificant = isSecondary
        ? isSecondaryMetricSignificant(metricIndex)
        : isPrimaryMetricSignificant(metricIndex)
    const result: { color: LemonTagType; label: string } = isSignificant
        ? { color: 'success', label: 'Significant' }
        : { color: 'primary', label: 'Not significant' }

    const inner = isSignificant ? (
        <div className="bg-success-highlight text-success-light px-1.5 py-0.5 flex items-center gap-1 rounded border border-success-light">
            <IconTrending fontSize={20} fontWeight={600} />
            <span className="text-xs font-semibold">{result.label}</span>
        </div>
    ) : (
        <div className="bg-warning-highlight text-warning-dark px-1.5 py-0.5 flex items-center gap-1 rounded border border-warning">
            <IconMinus fontSize={20} fontWeight={600} />
            <span className="text-xs font-semibold">{result.label}</span>
        </div>
    )

    const details = significanceDetails(metricIndex)

    return details ? (
        <Tooltip title={details}>
            <div
                className={clsx({
                    'cursor-default': true,
                    'bg-[var(--bg-table)]': true,
                    [className]: true,
                })}
            >
                {inner}
            </div>
        </Tooltip>
    ) : (
        <div className={clsx({ 'bg-[var(--bg-table)]': true, [className]: true })}>{inner}</div>
    )
}
