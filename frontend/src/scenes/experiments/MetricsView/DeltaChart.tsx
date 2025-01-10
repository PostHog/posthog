import {
    IconActivity,
    IconArrowRight,
    IconFunnels,
    IconGraph,
    IconMinus,
    IconPencil,
    IconTrending,
} from '@posthog/icons'
import { LemonBanner, LemonButton, LemonModal, LemonTag, LemonTagType, Tooltip } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { LemonProgress } from 'lib/lemon-ui/LemonProgress'
import { humanFriendlyNumber } from 'lib/utils'
import { useEffect, useRef, useState } from 'react'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'
import { InsightType, TrendExperimentVariant } from '~/types'

import { experimentLogic } from '../experimentLogic'
import { ExploreButton, ResultsQuery, VariantTag } from '../ExperimentView/components'
import { SignificanceText, WinningVariantText } from '../ExperimentView/Overview'
import { SummaryTable } from '../ExperimentView/SummaryTable'
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
const getMetricTitle = (metric: any, metricType: InsightType): JSX.Element => {
    if (metric.name) {
        return <span className="truncate">{metric.name}</span>
    }

    if (metricType === InsightType.TRENDS && metric.count_query?.series?.[0]?.name) {
        return <span className="truncate">{metric.count_query.series[0].name}</span>
    }

    if (metricType === InsightType.FUNNELS && metric.funnels_query?.series) {
        const series = metric.funnels_query.series
        if (series.length > 0) {
            const firstStep = series[0]?.name
            const lastStep = series[series.length - 1]?.name

            return (
                <span className="inline-flex items-center gap-1 min-w-0">
                    <IconFunnels className="text-muted flex-shrink-0" fontSize="14" />
                    <span className="truncate">{firstStep}</span>
                    <IconArrowRight className="text-muted flex-shrink-0" fontSize="14" />
                    <span className="truncate">{lastStep}</span>
                </span>
            )
        }
    }

    return <span className="text-muted truncate">Untitled metric</span>
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
        countDataForVariant,
        exposureCountDataForVariant,
        metricResultsLoading,
    } = useValues(experimentLogic)

    const { experiment } = useValues(experimentLogic)
    const {
        openPrimaryMetricModal,
        openSecondaryMetricModal,
        openPrimarySharedMetricModal,
        openSecondarySharedMetricModal,
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

    const BAR_HEIGHT = 10 + getScaleAddition(variants.length)
    const FIRST_BAR_PADDING = 6
    const LAST_BAR_PADDING = 6
    const BAR_PADDING = 14 + getScaleAddition(variants.length)
    const TICK_PANEL_HEIGHT = 20
    const VIEW_BOX_WIDTH = 800
    const HORIZONTAL_PADDING = 20
    const CONVERSION_RATE_RECT_WIDTH = 2
    const TICK_FONT_SIZE = 9

    const { isDarkModeOn } = useValues(themeLogic)
    const COLORS = {
        TICK_TEXT_COLOR: 'var(--text-secondary-3000)',
        BOUNDARY_LINES: 'var(--border-3000)',
        ZERO_LINE: 'var(--border-bold)',
        BAR_NEGATIVE: isDarkModeOn ? '#c32f45' : '#f84257',
        BAR_POSITIVE: isDarkModeOn ? '#12a461' : '#36cd6f',
        BAR_DEFAULT: isDarkModeOn ? 'rgb(121 121 121)' : 'rgb(217 217 217)',
        BAR_CONTROL: isDarkModeOn ? 'rgba(217, 217, 217, 0.2)' : 'rgba(217, 217, 217, 0.4)',
        BAR_MIDDLE_POINT: 'black',
        BAR_MIDDLE_POINT_CONTROL: 'rgba(0, 0, 0, 0.4)',
    }

    // Update chart height calculation to include only one BAR_PADDING for each space between bars
    const chartHeight =
        FIRST_BAR_PADDING + LAST_BAR_PADDING + BAR_PADDING + (BAR_HEIGHT + BAR_PADDING) * variants.length

    const valueToX = (value: number): number => {
        // Scale the value to fit within the padded area
        const percentage = (value / chartBound + 1) / 2
        return HORIZONTAL_PADDING + percentage * (VIEW_BOX_WIDTH - 2 * HORIZONTAL_PADDING)
    }

    const metricTitlePanelWidth = '25%'

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
    }, [])

    return (
        <div className="rounded bg-[var(--bg-table)] flex">
            {/* Metric title panel */}
            {/* eslint-disable-next-line react/forbid-dom-props */}
            <div style={{ width: metricTitlePanelWidth, verticalAlign: 'top' }}>
                {isFirstMetric && (
                    <svg
                        // eslint-disable-next-line react/forbid-dom-props
                        style={{ height: `${ticksSvgHeight}px` }}
                    />
                )}
                {isFirstMetric && <div className="w-full border-t border-border" />}
                <div
                    // eslint-disable-next-line react/forbid-dom-props
                    style={{ height: `${chartSvgHeight}px`, borderRight: `1px solid ${COLORS.BOUNDARY_LINES}` }}
                    className="p-2 overflow-auto"
                >
                    <div className="text-xs font-semibold whitespace-nowrap overflow-hidden">
                        <div className="space-y-1 pl-1">
                            <div className="flex items-center gap-2">
                                <div className="cursor-default text-xs font-semibold whitespace-nowrap overflow-hidden text-ellipsis flex-grow flex items-center">
                                    <span className="mr-1">{metricIndex + 1}.</span>
                                    {getMetricTitle(metric, metricType)}
                                </div>
                                <LemonButton
                                    className="flex-shrink-0"
                                    type="secondary"
                                    size="xsmall"
                                    icon={<IconPencil fontSize="12" />}
                                    onClick={() => {
                                        if (metric.isSharedMetric) {
                                            if (isSecondary) {
                                                openSecondarySharedMetricModal(metric.sharedMetricId)
                                            } else {
                                                openPrimarySharedMetricModal(metric.sharedMetricId)
                                            }
                                            return
                                        }
                                        isSecondary
                                            ? openSecondaryMetricModal(metricIndex)
                                            : openPrimaryMetricModal(metricIndex)
                                    }}
                                />
                            </div>
                            <div className="space-x-1">
                                <LemonTag type="muted" size="small">
                                    {metric.kind === 'ExperimentFunnelsQuery' ? 'Funnel' : 'Trend'}
                                </LemonTag>
                                {metric.isSharedMetric && (
                                    <LemonTag type="option" size="small">
                                        Shared
                                    </LemonTag>
                                )}
                            </div>
                        </div>
                    </div>
                </div>
            </div>
            {/* SVGs container */}
            <div
                // eslint-disable-next-line react/forbid-dom-props
                style={{
                    width: `calc(100% - ${metricTitlePanelWidth})`,
                    verticalAlign: 'top',
                }}
            >
                {/* Ticks */}
                {isFirstMetric && (
                    <svg
                        ref={ticksSvgRef}
                        viewBox={`0 0 ${VIEW_BOX_WIDTH} ${TICK_PANEL_HEIGHT}`}
                        preserveAspectRatio="xMidYMid meet"
                        // eslint-disable-next-line react/forbid-dom-props
                        style={{ minHeight: `${TICK_PANEL_HEIGHT}px` }}
                        className="pl-14"
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
                )}
                {isFirstMetric && <div className="w-full border-t border-border" />}
                {/* Chart */}
                {result ? (
                    <div className="relative pl-14">
                        <SignificanceHighlight
                            className="absolute top-2 left-2"
                            metricIndex={metricIndex}
                            isSecondary={isSecondary}
                        />
                        {isSecondary ||
                            (!isSecondary && experiment.metrics.length > 1 && (
                                <div className="absolute bottom-2 left-2 flex justify-center">
                                    <LemonButton
                                        type="secondary"
                                        size="xsmall"
                                        icon={<IconGraph />}
                                        onClick={() => setIsModalOpen(true)}
                                    >
                                        Details
                                    </LemonButton>
                                </div>
                            ))}
                        <svg
                            ref={chartSvgRef}
                            viewBox={`0 0 ${VIEW_BOX_WIDTH} ${chartHeight}`}
                            preserveAspectRatio="xMidYMid meet"
                            // eslint-disable-next-line react/forbid-dom-props
                            style={{ minHeight: `${chartHeight}px` }}
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
                                    delta = variantRate && controlRate ? (variantRate - controlRate) / controlRate : 0
                                }

                                const y = FIRST_BAR_PADDING + BAR_PADDING + (BAR_HEIGHT + BAR_PADDING) * index
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
                                            // Control variant - single gray bar
                                            <>
                                                <rect
                                                    x={x1}
                                                    y={y}
                                                    width={x2 - x1}
                                                    height={BAR_HEIGHT}
                                                    fill="transparent"
                                                />
                                                <rect
                                                    x={x1}
                                                    y={y}
                                                    width={x2 - x1}
                                                    height={BAR_HEIGHT}
                                                    fill={COLORS.BAR_CONTROL}
                                                    stroke={COLORS.BOUNDARY_LINES}
                                                    strokeWidth={1}
                                                    strokeDasharray="2,2"
                                                    rx={4}
                                                    ry={4}
                                                />
                                            </>
                                        ) : (
                                            // Test variants - split into positive and negative sections if needed
                                            <>
                                                <rect
                                                    x={x1}
                                                    y={y}
                                                    width={x2 - x1}
                                                    height={BAR_HEIGHT}
                                                    fill="transparent"
                                                />
                                                {lower < 0 && upper > 0 ? (
                                                    // Bar spans across zero - need to split
                                                    <>
                                                        <path
                                                            d={`
                                                                M ${x1 + 4} ${y}
                                                                H ${valueToX(0)}
                                                                V ${y + BAR_HEIGHT}
                                                                H ${x1 + 4}
                                                                Q ${x1} ${y + BAR_HEIGHT} ${x1} ${y + BAR_HEIGHT - 4}
                                                                V ${y + 4}
                                                                Q ${x1} ${y} ${x1 + 4} ${y}
                                                            `}
                                                            fill={COLORS.BAR_NEGATIVE}
                                                        />
                                                        <path
                                                            d={`
                                                                M ${valueToX(0)} ${y}
                                                                H ${x2 - 4}
                                                                Q ${x2} ${y} ${x2} ${y + 4}
                                                                V ${y + BAR_HEIGHT - 4}
                                                                Q ${x2} ${y + BAR_HEIGHT} ${x2 - 4} ${y + BAR_HEIGHT}
                                                                H ${valueToX(0)}
                                                                V ${y}
                                                            `}
                                                            fill={COLORS.BAR_POSITIVE}
                                                        />
                                                    </>
                                                ) : (
                                                    // Bar is entirely positive or negative
                                                    <rect
                                                        x={x1}
                                                        y={y}
                                                        width={x2 - x1}
                                                        height={BAR_HEIGHT}
                                                        fill={upper <= 0 ? COLORS.BAR_NEGATIVE : COLORS.BAR_POSITIVE}
                                                        rx={4}
                                                        ry={4}
                                                    />
                                                )}
                                            </>
                                        )}
                                        {/* Delta marker */}
                                        <rect
                                            x={deltaX - CONVERSION_RATE_RECT_WIDTH / 2}
                                            y={y}
                                            width={CONVERSION_RATE_RECT_WIDTH}
                                            height={BAR_HEIGHT}
                                            fill={
                                                variant.key === 'control'
                                                    ? COLORS.BAR_MIDDLE_POINT_CONTROL
                                                    : COLORS.BAR_MIDDLE_POINT
                                            }
                                        />
                                    </g>
                                )
                            })}
                        </svg>
                    </div>
                ) : metricResultsLoading ? (
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
                                className="flex items-center justify-center text-muted cursor-default"
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
                            <foreignObject
                                x={VIEW_BOX_WIDTH / 2 - 100}
                                y={chartHeight / 2 - 10}
                                width="250"
                                height="20"
                            >
                                <div
                                    className="flex items-center justify-center text-muted cursor-default"
                                    // eslint-disable-next-line react/forbid-dom-props
                                    style={{ fontSize: '10px', fontWeight: 400 }}
                                >
                                    <span>Waiting for experiment to start&hellip;</span>
                                </div>
                            </foreignObject>
                        ) : (
                            <foreignObject
                                x={VIEW_BOX_WIDTH / 2 - 100 - (result ? 0 : 200)}
                                y={chartHeight / 2 - 10}
                                width="250"
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
                                    className="flex items-center justify-center text-muted cursor-default"
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
                                                {metricType === InsightType.TRENDS ? '5' : '4'}
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
                            backgroundColor: 'var(--bg-light)',
                            border: '1px solid var(--border)',
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
                                <span className="text-muted font-semibold mb-1">Win probability:</span>
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
                                        <span className="text-muted font-semibold">
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
                                        <span className="text-muted font-semibold">Exposure:</span>
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
                                        <span className="text-muted font-semibold">Mean:</span>
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
                                    <span className="text-muted font-semibold">Conversion rate:</span>
                                    <span className="font-semibold">
                                        {conversionRateForVariant(result, tooltipData.variant)?.toFixed(2)}%
                                    </span>
                                </div>
                            )}
                            <div className="flex justify-between items-center">
                                <span className="text-muted font-semibold">Delta:</span>
                                <span className="font-semibold">
                                    {tooltipData.variant === 'control' ? (
                                        <em className="text-muted">Baseline</em>
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
                                <span className="text-muted font-semibold">Credible interval:</span>
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
                            backgroundColor: 'var(--bg-light)',
                            border: '1px solid var(--border)',
                            padding: '8px 12px',
                            borderRadius: '6px',
                            fontSize: '13px',
                            boxShadow: '0 4px 12px rgba(0, 0, 0, 0.1)',
                            pointerEvents: 'none',
                            zIndex: 100,
                            minWidth: '200px',
                        }}
                    >
                        <NoResultEmptyState error={error} />
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
                <div className="flex justify-end">
                    <ExploreButton result={result} />
                </div>
                <LemonBanner type="info" className="mb-4">
                    <div className="items-center inline-flex flex-wrap">
                        <WinningVariantText result={result} experimentId={experimentId} />
                        <SignificanceText metricIndex={metricIndex} />
                    </div>
                </LemonBanner>
                <SummaryTable metric={metric} metricIndex={metricIndex} isSecondary={isSecondary} />
                <ResultsQuery result={result} showTable={true} />
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
        <div className="bg-success-highlight text-success-dark px-1 py-0.5 flex items-center gap-1 rounded border border-success">
            <IconTrending fontSize={20} fontWeight={600} />
            <span className="text-xs font-semibold">{result.label}</span>
        </div>
    ) : (
        <div className="bg-warning-highlight text-warning-dark px-1 py-0.5 flex items-center gap-1 rounded border border-warning">
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
                    'bg-white': true,
                    [className]: true,
                })}
            >
                {inner}
            </div>
        </Tooltip>
    ) : (
        <div className={clsx({ 'bg-white': true, [className]: true })}>{inner}</div>
    )
}
