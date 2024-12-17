import { useValues } from 'kea'
import { useEffect, useRef, useState } from 'react'

import { InsightType } from '~/types'

import { experimentLogic } from '../experimentLogic'
import { VariantTag } from './components'

const BAR_HEIGHT = 8
const BAR_PADDING = 10
const TICK_PANEL_HEIGHT = 20
const VIEW_BOX_WIDTH = 800
const HORIZONTAL_PADDING = 20
const CONVERSION_RATE_RECT_WIDTH = 2
const TICK_FONT_SIZE = 7

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
    const { experiment, experimentResults, getMetricType, metricResults } = useValues(experimentLogic)

    if (!experimentResults) {
        return <></>
    }

    const variants = experiment.parameters.feature_flag_variants
    const allResults = [...(metricResults || [])]

    return (
        <div className="w-full overflow-x-auto">
            <div className="min-w-[800px]">
                {allResults.map((results, metricIndex) => {
                    if (!results) {
                        return null
                    }

                    const isFirstMetric = metricIndex === 0

                    return (
                        <div
                            key={metricIndex}
                            className={`w-full border border-border bg-light ${
                                allResults.length === 1
                                    ? 'rounded'
                                    : isFirstMetric
                                    ? 'rounded-t'
                                    : metricIndex === allResults.length - 1
                                    ? 'rounded-b'
                                    : ''
                            }`}
                        >
                            <Chart
                                results={results}
                                variants={variants}
                                metricType={getMetricType(metricIndex)}
                                isFirstMetric={isFirstMetric}
                            />
                        </div>
                    )
                })}
            </div>
        </div>
    )
}

function Chart({
    results,
    variants,
    metricType,
    isFirstMetric,
}: {
    results: any
    variants: any[]
    metricType: InsightType
    isFirstMetric: boolean
}): JSX.Element {
    const { credibleIntervalForVariant, conversionRateForVariant, experimentId } = useValues(experimentLogic)
    const [tooltipData, setTooltipData] = useState<{ x: number; y: number; variant: string } | null>(null)

    // Update chart height calculation to include only one BAR_PADDING for each space between bars
    const chartHeight = BAR_PADDING + (BAR_HEIGHT + BAR_PADDING) * variants.length

    // Find the maximum absolute value from all credible intervals
    const maxAbsValue = Math.max(
        ...variants.flatMap((variant) => {
            const interval = credibleIntervalForVariant(results, variant.key, metricType)
            return interval ? [Math.abs(interval[0] / 100), Math.abs(interval[1] / 100)] : []
        })
    )

    // Add padding to the range
    const padding = Math.max(maxAbsValue * 0.05, 0.02)
    const chartBound = maxAbsValue + padding

    const tickValues = getNiceTickValues(chartBound)
    const maxTick = Math.max(...tickValues)

    const valueToX = (value: number): number => {
        // Scale the value to fit within the padded area
        const percentage = (value / maxTick + 1) / 2
        return HORIZONTAL_PADDING + percentage * (VIEW_BOX_WIDTH - 2 * HORIZONTAL_PADDING)
    }

    const infoPanelWidth = '10%'

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
        <div className="w-full">
            {/* eslint-disable-next-line react/forbid-dom-props */}
            <div style={{ display: 'inline-block', width: infoPanelWidth, verticalAlign: 'top' }}>
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
                            <VariantTag experimentId={experimentId} variantKey={variant.key} fontSize={13} muted />
                        </div>
                    ))}
                </div>
            </div>

            {/* SVGs container */}
            <div
                // eslint-disable-next-line react/forbid-dom-props
                style={{
                    display: 'inline-block',
                    width: `calc(100% - ${infoPanelWidth})`,
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
                        const interval = credibleIntervalForVariant(results, variant.key, metricType)
                        const [lower, upper] = interval ? [interval[0] / 100, interval[1] / 100] : [0, 0]

                        const variantRate = conversionRateForVariant(results, variant.key)
                        const controlRate = conversionRateForVariant(results, 'control')
                        const delta = variantRate && controlRate ? (variantRate - controlRate) / controlRate : 0

                        // Find the highest delta among all variants
                        const maxDelta = Math.max(
                            ...variants.map((v) => {
                                const vRate = conversionRateForVariant(results, v.key)
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
                                <span className="text-[var(--content-tertiary)] font-semibold">Conversion rate:</span>
                                <span className="font-semibold">
                                    {conversionRateForVariant(results, tooltipData.variant)?.toFixed(2)}%
                                </span>
                            </div>
                            <div className="flex justify-between items-center">
                                <span className="text-[var(--content-tertiary)] font-semibold">Delta:</span>
                                <span className="font-semibold">
                                    {tooltipData.variant === 'control' ? (
                                        <em className="text-[var(--content-tertiary)]">Baseline</em>
                                    ) : (
                                        (() => {
                                            const variantRate = conversionRateForVariant(results, tooltipData.variant)
                                            const controlRate = conversionRateForVariant(results, 'control')
                                            const delta =
                                                variantRate && controlRate
                                                    ? (variantRate - controlRate) / controlRate
                                                    : 0
                                            return delta ? (
                                                <span
                                                    className={
                                                        delta > 0 ? 'text-[var(--content-success)]' : 'text-danger'
                                                    }
                                                >
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
                                <span className="text-[var(--content-tertiary)] font-semibold">Credible interval:</span>
                                <span className="font-semibold">
                                    {(() => {
                                        const interval = credibleIntervalForVariant(
                                            results,
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
            </div>
        </div>
    )
}
