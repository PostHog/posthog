import React, { useCallback, useEffect, useMemo, useState } from 'react'

import { useChartLayout } from '../../core/chart-context'
import type {
    BarChartConfig,
    BarsConfig,
    ChartLegendConfig,
    ChartMargins,
    ChartTheme,
    PointClickData,
    Series,
    TooltipConfig,
    TooltipContext,
} from '../../core/types'
import { BarChart } from '../BarChart/BarChart'

/** Inner gap between variant bars as a fraction of a step's band slot. */
export const FUNNEL_BAND_PADDING = 0.1

const FUNNEL_BAR_SHADOW: BarsConfig['shadow'] = { color: 'rgba(0,0,0,0.15)', blur: 6, offsetY: -2 }
const DEFAULT_CORNER_RADIUS = 10

export interface FunnelChartConfig {
    /** Tooltip behaviour + built-in content formatting. Defaults to `top` placement with a
     *  percent value formatter and step names in the header. */
    tooltip?: TooltipConfig
    /** Built-in legend with click-to-toggle series visibility. Hidden by default. */
    legend?: ChartLegendConfig
    animateHover?: boolean | number
    margins?: Partial<ChartMargins>
    /** Show horizontal grid lines at value-axis ticks. Defaults to true. */
    showGrid?: boolean
    /** Corner radius of the bar tops. Defaults to 10. */
    barCornerRadius?: number
    /** Hide the built-in step-name labels under the plot. Implied when `stepFooter` is set —
     *  the footer row replaces the axis labels. */
    hideStepLabels?: boolean
    /** Hide the percent value axis. */
    hideValueAxis?: boolean
    /** Truncate long step-name labels to this px width (ellipsis + hover reveal). */
    maxCategoryLabelWidth?: number
    /** Inner gap between variant bars as a fraction of the band slot. Defaults to {@link FUNNEL_BAND_PADDING}. */
    bandPadding?: number
    /** Cap (px) on the band-axis range — clusters steps at the start of the plot instead of
     *  stretching a 2–3 step funnel across the full width. */
    maxBandRange?: number
    /** Min pixel height of the chart region when `stepFooter` is set, so a tall footer can't
     *  collapse the canvas to zero height in a height-constrained parent. */
    chartMinHeight?: number
}

export interface FunnelStepClickData<Meta = unknown> extends PointClickData<Meta> {
    /** Index into `steps` of the clicked band. Same value as `dataIndex`, named for funnel call sites. */
    stepIndex: number
    /** True when the filled (converted) portion of a bar was clicked; false for the hatched
     *  drop-off track above it. */
    converted: boolean
}

/** Pixel box of one step's bars, relative to the chart wrapper. */
interface StepBand {
    left: number
    width: number
}

export interface FunnelChartProps<Meta = unknown> {
    /** Step display labels, in order. Duplicates are fine — bands are keyed by step index
     *  internally, so two steps sharing an event name keep separate slots. */
    steps: string[]
    /** One series per variant (a single series without a breakdown); `data[stepIndex]` is the
     *  conversion from the first step as a percent (0–100). The hatched track drawn behind each
     *  bar covers the remainder up to 100%. See `funnelFromCounts` for the raw-counts case. */
    series: Series<Meta>[]
    theme: ChartTheme
    config?: FunnelChartConfig
    /** Custom tooltip content. Omit for the built-in tooltip with percent formatting. */
    tooltip?: (ctx: TooltipContext<Meta>) => React.ReactNode
    /** Click on a bar (converted) or its drop-off track. Replaces `onPointClick`. */
    onStepClick?: (data: FunnelStepClickData<Meta>) => void
    /** Per-step content rendered in a row below the plot, horizontally aligned under each
     *  step's bars — for step legends richer than an axis label. Hides the built-in step labels. */
    stepFooter?: (stepIndex: number) => React.ReactNode
    dataAttr?: string
    className?: string
    children?: React.ReactNode
    onError?: (error: Error, info: React.ErrorInfo) => void
}

function formatPercent(value: number): string {
    return `${parseFloat(value.toFixed(2))}%`
}

/** Reports each band's pixel box up to the wrapper so the step-footer row can align its cells
 *  under the bars without duplicating the chart's band math. Renders nothing. */
function StepBandProbe({ onBands }: { onBands: (bands: StepBand[]) => void }): null {
    const { scales, labels } = useChartLayout()
    const bands = useMemo(
        () =>
            labels.map((label): StepBand => {
                const center = scales.x(label) ?? 0
                const width = scales.extent?.(label) ?? 0
                return { left: center - width / 2, width }
            }),
        [scales, labels]
    )
    useEffect(() => onBands(bands), [bands, onBands])
    return null
}

function StepFooterRow({
    bands,
    stepFooter,
}: {
    bands: StepBand[]
    stepFooter: (stepIndex: number) => React.ReactNode
}): React.ReactElement {
    // One gutter column before each band column, so cells sit in normal flow (the row grows to
    // the tallest cell) while staying pixel-aligned with the bars above.
    const columns: string[] = []
    let cursor = 0
    for (const band of bands) {
        columns.push(`${Math.max(0, band.left - cursor)}px`, `${band.width}px`)
        cursor = band.left + band.width
    }
    return (
        // eslint-disable-next-line react/forbid-dom-props
        <div
            className="grid shrink-0"
            style={{ gridTemplateColumns: columns.join(' ') }}
            data-attr="hog-funnel-step-footer"
        >
            {bands.map((_, stepIndex) => (
                // eslint-disable-next-line react/forbid-dom-props
                <div
                    key={stepIndex}
                    className="min-w-0"
                    style={{ gridColumn: 2 * stepIndex + 2, gridRow: 1 }}
                    data-attr="hog-funnel-step-footer-cell"
                >
                    {stepFooter(stepIndex)}
                </div>
            ))}
        </div>
    )
}

/** Funnel steps as grouped vertical bars — each step a band, each variant a bar valued by its
 *  conversion from the first step, with a hatched track behind it covering the drop-off remainder.
 *  A thin wrapper over {@link BarChart}; overlays compose as children the same way. */
export function FunnelChart<Meta = unknown>({
    steps,
    series,
    theme,
    config,
    tooltip,
    onStepClick,
    stepFooter,
    dataAttr,
    className,
    children,
    onError,
}: FunnelChartProps<Meta>): React.ReactElement {
    const {
        tooltip: tooltipConfig,
        legend,
        animateHover,
        margins,
        showGrid = true,
        barCornerRadius = DEFAULT_CORNER_RADIUS,
        hideStepLabels,
        hideValueAxis,
        maxCategoryLabelWidth,
        bandPadding,
        maxBandRange,
        chartMinHeight,
    } = config ?? {}
    const hasStepFooter = stepFooter != null

    // Band labels are 1-based step indices so steps sharing a name don't collapse onto one
    // d3 band slot; formatters map them back to the display label.
    const bandLabels = useMemo(() => steps.map((_, stepIndex) => `${stepIndex + 1}`), [steps])
    const stepLabelFromBand = useCallback((band: string): string => steps[Number(band) - 1] ?? band, [steps])

    const barConfig = useMemo<BarChartConfig>(
        () => ({
            barLayout: 'grouped',
            showGrid,
            animateHover,
            margins,
            hideXAxis: hideStepLabels || hasStepFooter,
            hideYAxis: hideValueAxis,
            maxCategoryLabelWidth,
            xTickFormatter: stepLabelFromBand,
            yTickFormatter: (value) => `${Math.round(value)}%`,
            barCornerRadius,
            legend,
            tooltip: {
                placement: 'top',
                valueFormatter: formatPercent,
                labelFormatter: stepLabelFromBand,
                ...tooltipConfig,
            },
            bars: {
                track: true,
                shadow: FUNNEL_BAR_SHADOW,
                bandPadding: bandPadding ?? FUNNEL_BAND_PADDING,
                maxBandRange,
            },
        }),
        [
            showGrid,
            animateHover,
            margins,
            hideStepLabels,
            hasStepFooter,
            hideValueAxis,
            maxCategoryLabelWidth,
            stepLabelFromBand,
            legend,
            tooltipConfig,
            barCornerRadius,
            bandPadding,
            maxBandRange,
        ]
    )

    const handlePointClick = useMemo(
        () =>
            onStepClick
                ? (data: PointClickData<Meta>): void =>
                      onStepClick({ ...data, stepIndex: data.dataIndex, converted: !data.inTrackArea })
                : undefined,
        [onStepClick]
    )

    const [bands, setBands] = useState<StepBand[] | null>(null)

    const chart = (
        <BarChart<Meta>
            series={series}
            labels={bandLabels}
            theme={theme}
            config={barConfig}
            tooltip={tooltip}
            onPointClick={handlePointClick}
            className={className}
            dataAttr={dataAttr}
            onError={onError}
        >
            {hasStepFooter && <StepBandProbe onBands={setBands} />}
            {children}
        </BarChart>
    )

    if (!stepFooter) {
        return chart
    }

    return (
        <div className="flex flex-col flex-1 min-h-0">
            {/* Flex column so the chart stretches into the min-height floor. */}
            {/* eslint-disable-next-line react/forbid-dom-props */}
            <div
                className="flex flex-col flex-1 min-h-0"
                style={chartMinHeight != null ? { minHeight: chartMinHeight } : undefined}
                data-attr="hog-funnel-chart-region"
            >
                {chart}
            </div>
            {bands && bands.length > 0 && <StepFooterRow bands={bands} stepFooter={stepFooter} />}
        </div>
    )
}
