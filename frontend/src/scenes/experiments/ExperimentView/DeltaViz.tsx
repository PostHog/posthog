import { useValues, useActions } from 'kea'
import { useEffect, useRef, useState } from 'react'

import { InsightType } from '~/types'

import { experimentLogic, getDefaultFilters, getDefaultFunnelsMetric } from '../experimentLogic'
import { VariantTag } from './components'
import { LemonButton, LemonTag } from '@posthog/lemon-ui'
import { IconArchive, IconCheck, IconPencil, IconPlus, IconX, IconHourglass } from '@posthog/icons'
import { FEATURE_FLAGS } from 'lib/constants'

const MAX_PRIMARY_METRICS = 10

const BAR_HEIGHT = 8
const BAR_PADDING = 10
const TICK_PANEL_HEIGHT = 20
const VIEW_BOX_WIDTH = 800
const HORIZONTAL_PADDING = 20
const CONVERSION_RATE_RECT_WIDTH = 2
const TICK_FONT_SIZE = 9

const COLORS = {
    BOUNDARY_LINES: '#d0d0d0',
    ZERO_LINE: '#666666',
    BAR_NEGATIVE: '#F44435',
    BAR_BEST: '#4DAF4F',
    BAR_DEFAULT: '#d9d9d9',
    BAR_CONTROL: 'rgba(217, 217, 217, 0.4)',
    BAR_MIDDLE_POINT: 'black',
    BAR_MIDDLE_POINT_CONTROL: 'rgba(0, 0, 0, 0.4)',
}

// Helper function to find nice round numbers for ticks
export function getNiceTickValues(maxAbsValue: number): number[] {
    // Round up maxAbsValue to ensure we cover all values
    maxAbsValue = Math.ceil(maxAbsValue * 10) / 10

    const magnitude = Math.floor(Math.log10(maxAbsValue))
    const power = Math.pow(10, magnitude)

    let baseUnit
    const normalizedMax = maxAbsValue / power
    if (normalizedMax <= 1) {
        baseUnit = 0.2 * power
    } else if (normalizedMax <= 2) {
        baseUnit = 0.5 * power
    } else if (normalizedMax <= 5) {
        baseUnit = 1 * power
    } else {
        baseUnit = 2 * power
    }

    // Calculate how many baseUnits we need to exceed maxAbsValue
    const unitsNeeded = Math.ceil(maxAbsValue / baseUnit)

    // Determine appropriate number of decimal places based on magnitude
    const decimalPlaces = Math.max(0, -magnitude + 1)

    const ticks: number[] = []
    for (let i = -unitsNeeded; i <= unitsNeeded; i++) {
        // Round each tick value to avoid floating point precision issues
        const tickValue = Number((baseUnit * i).toFixed(decimalPlaces))
        ticks.push(tickValue)
    }
    return ticks
}

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

export function DeltaViz(): JSX.Element {
    const { experiment, getMetricType, metricResults, primaryMetricsResultErrors, credibleIntervalForVariant } =
        useValues(experimentLogic)
    const { setExperiment, openPrimaryMetricModal } = useActions(experimentLogic)

    const variants = experiment.parameters.feature_flag_variants
    const metrics = experiment.metrics || []

    // Calculate the maximum absolute value across ALL metrics
    const maxAbsValue = Math.max(
        ...metrics.flatMap((_, metricIndex) => {
            const result = metricResults?.[metricIndex]
            return variants.flatMap((variant) => {
                const interval = credibleIntervalForVariant(result, variant.key, getMetricType(metricIndex))
                return interval ? [Math.abs(interval[0] / 100), Math.abs(interval[1] / 100)] : []
            })
        })
    )

    // Add padding to the range
    const padding = Math.max(maxAbsValue * 0.05, 0.02)
    const chartBound = maxAbsValue + padding

    // Calculate tick values once for all charts
    const commonTickValues = getNiceTickValues(chartBound)

    return (
        <div className="my-4">
            <div className="flex">
                <div className="w-1/2 pt-5">
                    <div className="inline-flex space-x-2 mb-0">
                        <h2 className="mb-1 font-semibold text-lg">Primary metrics</h2>
                    </div>
                </div>

                <div className="w-1/2 flex flex-col justify-end">
                    <div className="ml-auto">
                        <div className="mb-2 mt-4 justify-end">
                            <LemonButton
                                icon={<IconPlus />}
                                type="secondary"
                                size="small"
                                onClick={() => {
                                    const newMetrics = [...experiment.metrics, getDefaultFunnelsMetric()]
                                    setExperiment({
                                        metrics: newMetrics,
                                    })
                                    openPrimaryMetricModal(newMetrics.length - 1)
                                }}
                                disabledReason={
                                    metrics.length >= MAX_PRIMARY_METRICS
                                        ? `You can only add up to ${MAX_PRIMARY_METRICS} primary metrics.`
                                        : undefined
                                }
                            >
                                Add metric
                            </LemonButton>
                        </div>
                    </div>
                </div>
            </div>
            <div className="w-full overflow-x-auto">
                <div className="min-w-[800px]">
                    {metrics.map((metric, metricIndex) => {
                        const result = metricResults?.[metricIndex]
                        const isFirstMetric = metricIndex === 0

                        return (
                            <div
                                key={metricIndex}
                                className={`w-full border border-border bg-light ${
                                    metrics.length === 1
                                        ? 'rounded'
                                        : isFirstMetric
                                        ? 'rounded-t'
                                        : metricIndex === metrics.length - 1
                                        ? 'rounded-b'
                                        : ''
                                }`}
                            >
                                <Chart
                                    result={result}
                                    error={primaryMetricsResultErrors?.[metricIndex]}
                                    variants={variants}
                                    metricType={getMetricType(metricIndex)}
                                    metricIndex={metricIndex}
                                    isFirstMetric={isFirstMetric}
                                    metric={metric}
                                    tickValues={commonTickValues}
                                    chartBound={chartBound}
                                />
                            </div>
                        )
                    })}
                </div>
            </div>
        </div>
    )
}

function Chart({
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
    const { credibleIntervalForVariant, conversionRateForVariant, experimentId } = useValues(experimentLogic)
    const { openPrimaryMetricModal } = useActions(experimentLogic)
    const [tooltipData, setTooltipData] = useState<{ x: number; y: number; variant: string } | null>(null)
    const [emptyStateTooltipVisible, setEmptyStateTooltipVisible] = useState(true)
    const [tooltipPosition, setTooltipPosition] = useState({ x: 0, y: 0 })

    // Update chart height calculation to include only one BAR_PADDING for each space between bars
    const chartHeight = BAR_PADDING + (BAR_HEIGHT + BAR_PADDING) * variants.length

    const valueToX = (value: number): number => {
        // Scale the value to fit within the padded area
        const percentage = (value / chartBound + 1) / 2
        return HORIZONTAL_PADDING + percentage * (VIEW_BOX_WIDTH - 2 * HORIZONTAL_PADDING)
    }

    const metricTitlePanelWidth = '20%'
    const variantsPanelWidth = '10%'

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
                        <div className="space-y-1">
                            <div className="cursor-default text-xs font-semibold whitespace-nowrap overflow-hidden text-ellipsis">
                                {metricIndex + 1}. {metric.name || <span className="text-muted">Untitled metric</span>}
                            </div>
                            <LemonTag type="muted" size="small">
                                {metric.kind === 'ExperimentFunnelsQuery' ? 'Funnel' : 'Trend'}
                            </LemonTag>
                            <LemonButton
                                className="max-w-72"
                                type="secondary"
                                size="xsmall"
                                icon={<IconPencil />}
                                onClick={() => openPrimaryMetricModal(metricIndex)}
                            />
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
                        style={{ height: `${ticksSvgHeight}px` }}
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
                    width: `calc(100% - ${metricTitlePanelWidth} - ${variantsPanelWidth})`,
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
                                        fill="rgba(17, 17, 17, 0.7)"
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

                            const variantRate = conversionRateForVariant(result, variant.key)
                            const controlRate = conversionRateForVariant(result, 'control')
                            const delta = variantRate && controlRate ? (variantRate - controlRate) / controlRate : 0

                            // Find the highest delta among all variants
                            const maxDelta = Math.max(
                                ...variants.map((v) => {
                                    const vRate = conversionRateForVariant(result, v.key)
                                    return vRate && controlRate ? (vRate - controlRate) / controlRate : 0
                                })
                            )

                            let barColor
                            if (variant.key === 'control') {
                                barColor = COLORS.BAR_DEFAULT
                            } else if (delta < 0) {
                                barColor = COLORS.BAR_NEGATIVE
                            } else if (delta === maxDelta) {
                                barColor = COLORS.BAR_BEST
                            } else {
                                barColor = COLORS.BAR_DEFAULT
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
                                    {/* Invisible full-width rect to ensure consistent hover */}
                                    <rect x={x1} y={y} width={x2 - x1} height={BAR_HEIGHT} fill="transparent" />
                                    {/* Visible elements */}
                                    <rect
                                        x={x1}
                                        y={y}
                                        width={x2 - x1}
                                        height={BAR_HEIGHT}
                                        fill={variant.key === 'control' ? COLORS.BAR_CONTROL : barColor}
                                        stroke={variant.key === 'control' ? COLORS.BOUNDARY_LINES : 'none'}
                                        strokeWidth={1}
                                        strokeDasharray={variant.key === 'control' ? '2,2' : 'none'}
                                        rx={4}
                                        ry={4}
                                    />
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
                ) : (
                    // Empty state
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
                                <span>Results not yet available</span>
                                <IconHourglass style={{ marginLeft: 4, verticalAlign: 'middle' }} />
                            </div>
                        </foreignObject>
                    </svg>
                )}

                {/* Tooltip */}
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
                            <div className="flex justify-between items-center">
                                <span className="text-muted font-semibold">Conversion rate:</span>
                                <span className="font-semibold">
                                    {conversionRateForVariant(result, tooltipData.variant)?.toFixed(2)}%
                                </span>
                            </div>
                            <div className="flex justify-between items-center">
                                <span className="text-muted font-semibold">Delta:</span>
                                <span className="font-semibold">
                                    {tooltipData.variant === 'control' ? (
                                        <em className="text-muted">Baseline</em>
                                    ) : (
                                        (() => {
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
                        <NoResultsEmptyState error={error} />
                    </div>
                )}
            </div>
        </div>
    )
}

export function NoResultsEmptyState({ error }: { error: any }): JSX.Element {
    if (!error) {
        return <></>
    }

    type ErrorCode = 'no-events' | 'no-flag-info' | 'no-control-variant' | 'no-test-variant'

    const { statusCode } = error

    function ChecklistItem({ errorCode, value }: { errorCode: ErrorCode; value: boolean }): JSX.Element {
        const failureText = {
            'no-events': 'Metric events not received',
            'no-flag-info': 'Feature flag information not present on the events',
            'no-control-variant': 'Events with the control variant not received',
            'no-test-variant': 'Events with at least one test variant not received',
        }

        const successText = {
            'no-events': 'Experiment events have been received',
            'no-flag-info': 'Feature flag information is present on the events',
            'no-control-variant': 'Events with the control variant received',
            'no-test-variant': 'Events with at least one test variant received',
        }

        return (
            <div className="flex items-center space-x-2">
                {value === false ? (
                    <span className="flex items-center space-x-2">
                        <IconCheck className="text-success" fontSize={16} />
                        <span className="text-muted">{successText[errorCode]}</span>
                    </span>
                ) : (
                    <span className="flex items-center space-x-2">
                        <IconX className="text-danger" fontSize={16} />
                        <span>{failureText[errorCode]}</span>
                    </span>
                )}
            </div>
        )
    }

    // Validation errors return 400 and are rendered as a checklist
    if (statusCode === 400) {
        let parsedDetail: Record<ErrorCode, boolean>
        try {
            parsedDetail = JSON.parse(error.detail)
        } catch (error) {
            return (
                <div className="border rounded bg-bg-light p-4">
                    <div className="font-semibold leading-tight text-base text-current">
                        Experiment results could not be calculated
                    </div>
                    <div className="mt-2">{error}</div>
                </div>
            )
        }

        const checklistItems = []
        for (const [errorCode, value] of Object.entries(parsedDetail)) {
            checklistItems.push(<ChecklistItem key={errorCode} errorCode={errorCode as ErrorCode} value={value} />)
        }

        return <div>{checklistItems}</div>
    }

    if (statusCode === 504) {
        return (
            <div>
                <div className="border rounded bg-bg-light py-10">
                    <div className="flex flex-col items-center mx-auto text-muted space-y-2">
                        <IconArchive className="text-4xl text-secondary-3000" />
                        <h2 className="text-xl font-semibold leading-tight">Experiment results timed out</h2>
                        <div className="text-sm text-center text-balance">
                            This may occur when the experiment has a large amount of data or is particularly complex. We
                            are actively working on fixing this. In the meantime, please try refreshing the experiment
                            to retrieve the results.
                        </div>
                    </div>
                </div>
            </div>
        )
    }

    // Other unexpected errors
    return (
        <div>
            <div className="border rounded bg-bg-light py-10">
                <div className="flex flex-col items-center mx-auto text-muted space-y-2">
                    <IconArchive className="text-4xl text-secondary-3000" />
                    <h2 className="text-xl font-semibold leading-tight">Experiment results could not be calculated</h2>
                    <div className="text-sm text-center text-balance">{error.detail}</div>
                </div>
            </div>
        </div>
    )
}
