import { IconActivity, IconGraph, IconPencil } from '@posthog/icons'
import { LemonButton, LemonModal, LemonTag } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { humanFriendlyNumber } from 'lib/utils'
import { useEffect, useRef, useState } from 'react'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'
import { InsightType, TrendExperimentVariant } from '~/types'

import { experimentLogic } from '../experimentLogic'
import { ResultsQuery, VariantTag } from '../ExperimentView/components'
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

export function DeltaChart({
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
    const { openPrimaryMetricModal } = useActions(experimentLogic)
    const [tooltipData, setTooltipData] = useState<{ x: number; y: number; variant: string } | null>(null)
    const [emptyStateTooltipVisible, setEmptyStateTooltipVisible] = useState(true)
    const [tooltipPosition, setTooltipPosition] = useState({ x: 0, y: 0 })
    const [isModalOpen, setIsModalOpen] = useState(false)

    const BAR_HEIGHT = 8
    const BAR_PADDING = 10
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
        BAR_NEGATIVE: isDarkModeOn ? 'rgb(206 66 54)' : '#F44435',
        BAR_BEST: isDarkModeOn ? 'rgb(49 145 51)' : '#4DAF4F',
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
    const variantsPanelWidth = '10%'
    const detailedResultsPanelWidth = '10%'

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
        <div className="w-full rounded bg-[var(--bg-table)]">
            {/* Metric title panel */}
            {/* eslint-disable-next-line react/forbid-dom-props */}
            <div style={{ display: 'inline-block', width: metricTitlePanelWidth, verticalAlign: 'top' }}>
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
                    className="p-1 overflow-auto"
                >
                    <div className="text-xs font-semibold whitespace-nowrap overflow-hidden">
                        <div className="space-y-1 pl-1">
                            <div className="flex items-center gap-2">
                                <div className="cursor-default text-xs font-semibold whitespace-nowrap overflow-hidden text-ellipsis flex-grow">
                                    {metricIndex + 1}.{' '}
                                    {metric.name || <span className="text-muted">Untitled metric</span>}
                                </div>
                                <LemonButton
                                    className="flex-shrink-0"
                                    type="secondary"
                                    size="xsmall"
                                    icon={<IconPencil fontSize="12" />}
                                    onClick={() => openPrimaryMetricModal(metricIndex)}
                                />
                            </div>
                            <LemonTag type="muted" size="small">
                                {metric.kind === 'ExperimentFunnelsQuery' ? 'Funnel' : 'Trend'}
                            </LemonTag>
                        </div>
                    </div>
                </div>
            </div>

            {/* Variants panel */}
            {/* eslint-disable-next-line react/forbid-dom-props */}
            <div style={{ display: 'inline-block', width: variantsPanelWidth, verticalAlign: 'top' }}>
                {isFirstMetric && (
                    <svg
                        // eslint-disable-next-line react/forbid-dom-props
                        style={{ height: `${ticksSvgHeight}px`, width: '100%' }}
                    />
                )}
                {isFirstMetric && <div className="w-full border-t border-border" />}
                {/* eslint-disable-next-line react/forbid-dom-props */}
                <div style={{ height: `${chartSvgHeight}px` }}>
                    {variants.map((variant) => (
                        <div
                            key={variant.key}
                            // eslint-disable-next-line react/forbid-dom-props
                            style={{
                                height: `${100 / variants.length}%`,
                                display: 'flex',
                                alignItems: 'center',
                                paddingLeft: '10px',
                            }}
                        >
                            <VariantTag experimentId={experimentId} variantKey={variant.key} fontSize={11} muted />
                        </div>
                    ))}
                </div>
            </div>
            {/* SVGs container */}
            <div
                // eslint-disable-next-line react/forbid-dom-props
                style={{
                    display: 'inline-block',
                    width: `calc(100% - ${metricTitlePanelWidth} - ${variantsPanelWidth} - ${detailedResultsPanelWidth})`,
                    verticalAlign: 'top',
                }}
            >
                {/* Ticks */}
                {isFirstMetric && (
                    <svg
                        ref={ticksSvgRef}
                        viewBox={`0 0 ${VIEW_BOX_WIDTH} ${TICK_PANEL_HEIGHT}`}
                        preserveAspectRatio="xMidYMid meet"
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
                    <svg
                        ref={chartSvgRef}
                        viewBox={`0 0 ${VIEW_BOX_WIDTH} ${chartHeight}`}
                        preserveAspectRatio="xMidYMid meet"
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
                                >
                                    {variant.key === 'control' ? (
                                        // Control variant - single gray bar
                                        <>
                                            <rect x={x1} y={y} width={x2 - x1} height={BAR_HEIGHT} fill="transparent" />
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
                                            <rect x={x1} y={y} width={x2 - x1} height={BAR_HEIGHT} fill="transparent" />
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
                                                        fill={COLORS.BAR_BEST}
                                                    />
                                                </>
                                            ) : (
                                                // Bar is entirely positive or negative
                                                <rect
                                                    x={x1}
                                                    y={y}
                                                    width={x2 - x1}
                                                    height={BAR_HEIGHT}
                                                    fill={upper <= 0 ? COLORS.BAR_NEGATIVE : COLORS.BAR_BEST}
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
                                x={VIEW_BOX_WIDTH / 2 - 100}
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
                                                        const detail = JSON.parse(error.detail)
                                                        return Object.values(detail).filter((v) => v === false).length
                                                    } catch {
                                                        return '0'
                                                    }
                                                })()}
                                            </span>
                                            /<span className="font-semibold">4</span>
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
                            {metricType === InsightType.TRENDS ? (
                                <>
                                    <div className="flex justify-between items-center">
                                        <span className="text-muted font-semibold">Count:</span>
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
            {/* Detailed results panel */}
            <div
                // eslint-disable-next-line react/forbid-dom-props
                style={{
                    display: 'inline-block',
                    width: detailedResultsPanelWidth,
                    verticalAlign: 'top',
                }}
            >
                {isFirstMetric && (
                    <svg
                        // eslint-disable-next-line react/forbid-dom-props
                        style={{ height: `${ticksSvgHeight}px`, width: '100%' }}
                    />
                )}
                {isFirstMetric && <div className="w-full border-t border-border" />}
                {result && (
                    <div
                        // eslint-disable-next-line react/forbid-dom-props
                        style={{
                            height: `${chartSvgHeight}px`,
                            borderLeft: result ? `1px solid ${COLORS.BOUNDARY_LINES}` : 'none',
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'center',
                            padding: '0 4px',
                        }}
                    >
                        <LemonButton
                            type="secondary"
                            size="xsmall"
                            icon={<IconGraph />}
                            onClick={() => setIsModalOpen(true)}
                        >
                            Detailed results
                        </LemonButton>
                    </div>
                )}
            </div>

            <LemonModal
                isOpen={isModalOpen}
                onClose={() => setIsModalOpen(false)}
                width={1200}
                title={`Results for ${metric.name || 'Untitled metric'}`}
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
                <ResultsQuery targetResults={result} showTable={true} />
            </LemonModal>
        </div>
    )
}
