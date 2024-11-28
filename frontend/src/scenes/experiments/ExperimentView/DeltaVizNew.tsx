import { useEffect, useRef, useState } from 'react'
import { useValues } from 'kea'
import { Chart } from 'chart.js'
import { experimentLogic } from '../experimentLogic'
import { InsightType } from '~/types'
import { VariantTag } from './components'

// Dimensions
const BORDER_WIDTH = 4
const BAR_HEIGHT = 8
const BAR_PADDING = 10
const TICK_PANEL_HEIGHT = 20
const VIEW_BOX_WIDTH = 800
const HORIZONTAL_PADDING = 20
const CONVERSION_RATE_RECT_WIDTH = 2
const TICK_FONT_SIZE = 8

// Colors
const COLORS = {
    BOUNDARY_LINES: '#d0d0d0', // Darker gray for boundaries (changed from #e8e8e8)
    ZERO_LINE: '#666666', // Keeping zero line the darkest
    BAR_NEGATIVE: '#F44435', // Red for negative delta
    BAR_BEST: '#4DAF4F', // Green for best performer
    BAR_DEFAULT: '#d9d9d9', // Gray for other bars
    BAR_MIDDLE_POINT: 'black', // Black for the middle point marker
}

// Helper function to find nice round numbers for ticks
function getNiceTickValues(maxAbsValue: number): number[] {
    // First, round up maxAbsValue to ensure we cover all values
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

    const ticks: number[] = []
    // Use unitsNeeded instead of fixed 3
    for (let i = -unitsNeeded; i <= unitsNeeded; i++) {
        ticks.push(baseUnit * i)
    }
    return ticks
}

// Helper function to format percentage values
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

export function DeltaVizNew(): JSX.Element {
    const { experimentResults, tabularExperimentResults, getMetricType, metricResults } = useValues(experimentLogic)

    if (!experimentResults) {
        return <></>
    }

    const variants = tabularExperimentResults.filter((variant) => variant.key !== 'control')
    const allResults = [...(metricResults || [])]

    return (
        // eslint-disable-next-line react/forbid-dom-props
        <div style={{ width: '100%' }}>
            {allResults.map((results, metricIndex) => {
                if (!results) {
                    return null
                }

                const isFirstMetric = metricIndex === 0

                return (
                    <div
                        key={metricIndex}
                        // eslint-disable-next-line react/forbid-dom-props
                        style={{
                            width: '100%',
                            border: '1px solid #e8e8e8',
                            borderRadius: isFirstMetric
                                ? '4px 4px 0 0'
                                : metricIndex === allResults.length - 1
                                ? '0 0 4px 4px'
                                : '0',
                            backgroundColor: '#f9faf7',
                        }}
                    >
                        <DeltaChart
                            results={results}
                            variants={variants}
                            metricType={getMetricType(metricIndex)}
                            isFirstMetric={isFirstMetric}
                        />
                    </div>
                )
            })}
        </div>
    )
}

function DeltaChart({
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
            return [Math.abs(interval[0] / 100), Math.abs(interval[1] / 100)]
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

    return (
        <div style={{ width: '100%' }}>
            <div
                style={{
                    display: 'inline-block',
                    width: '200px',
                    verticalAlign: 'top',
                }}
            >
                {isFirstMetric && (
                    <div style={{ backgroundColor: 'pink' }}>
                        <span>top</span>
                    </div>
                )}

                <div
                    style={{
                        backgroundColor: 'lightblue',
                    }}
                >
                    bottom
                </div>
            </div>

            {/* SVGs container */}
            <div
                style={{
                    display: 'inline-block',
                    width: 'calc(100% - 200px)',
                    verticalAlign: 'top',
                }}
            >
                {isFirstMetric && (
                    <svg
                        viewBox={`0 0 ${VIEW_BOX_WIDTH} ${TICK_PANEL_HEIGHT}`}
                        preserveAspectRatio="xMidYMid meet"
                        style={{ backgroundColor: '#e8e8e8' }}
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
                                    >
                                        {formatTickValue(value)}
                                    </text>
                                </g>
                            )
                        })}
                    </svg>
                )}

                <svg viewBox={`0 0 ${VIEW_BOX_WIDTH} ${chartHeight}`} preserveAspectRatio="xMidYMid meet">
                    {/* Vertical grid lines */}
                    {tickValues.map((value, index) => {
                        const x = valueToX(value)
                        return (
                            <line
                                key={index}
                                x1={x}
                                y1={0}
                                x2={x}
                                y2={chartHeight}
                                stroke={value === 0 ? COLORS.ZERO_LINE : COLORS.BOUNDARY_LINES}
                                strokeWidth={value === 0 ? 1 : 0.5}
                            />
                        )
                    })}

                    {variants.map((variant, index) => {
                        const interval = credibleIntervalForVariant(results, variant.key, metricType)
                        const [lower, upper] = interval.map((v) => v / 100)

                        const variantRate = conversionRateForVariant(results, variant.key)
                        const controlRate = conversionRateForVariant(results, 'control')
                        const delta = (variantRate - controlRate) / controlRate

                        // Find the highest delta among all variants
                        const maxDelta = Math.max(
                            ...variants.map((v) => {
                                const vRate = conversionRateForVariant(results, v.key)
                                return (vRate - controlRate) / controlRate
                            })
                        )

                        let barColor
                        if (delta < 0) {
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
                                <rect x={x1} y={y} width={x2 - x1} height={BAR_HEIGHT} fill={barColor} rx={4} ry={4} />
                                <rect
                                    x={deltaX - CONVERSION_RATE_RECT_WIDTH / 2}
                                    y={y}
                                    width={CONVERSION_RATE_RECT_WIDTH}
                                    height={BAR_HEIGHT}
                                    fill="black"
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
                                <span className="text-muted font-semibold">Conversion rate:</span>
                                <span className="font-semibold">
                                    {conversionRateForVariant(results, tooltipData.variant)?.toFixed(2)}%
                                </span>
                            </div>
                            {tooltipData.variant !== 'control' && (
                                <>
                                    {(() => {
                                        const variantRate = conversionRateForVariant(results, tooltipData.variant)
                                        const controlRate = conversionRateForVariant(results, 'control')
                                        const delta = (variantRate - controlRate) / controlRate
                                        return (
                                            <div className="flex justify-between items-center">
                                                <span className="text-muted font-semibold">Delta:</span>
                                                <span
                                                    className={`font-semibold ${
                                                        delta > 0 ? 'text-success' : delta < 0 ? 'text-danger' : ''
                                                    }`}
                                                >
                                                    {delta
                                                        ? `${delta > 0 ? '+' : ''}${(delta * 100).toFixed(2)}%`
                                                        : '—'}
                                                </span>
                                            </div>
                                        )
                                    })()}
                                    {(() => {
                                        const interval = credibleIntervalForVariant(
                                            results,
                                            tooltipData.variant,
                                            metricType
                                        )
                                        const [lower, upper] = interval.map((v) => v / 100)
                                        return (
                                            <div className="flex justify-between items-center">
                                                <span className="text-muted font-semibold">Credible interval:</span>
                                                <span className="font-semibold">
                                                    {`[${lower > 0 ? '+' : ''}${(lower * 100).toFixed(2)}%, ${
                                                        upper > 0 ? '+' : ''
                                                    }${(upper * 100).toFixed(2)}%]`}
                                                </span>
                                            </div>
                                        )
                                    })()}
                                </>
                            )}
                        </div>
                    </div>
                )}
            </div>
        </div>
    )
}
