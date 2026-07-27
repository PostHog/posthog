import React, { useCallback, useMemo } from 'react'

import { ChartLegend } from '../../components/Legend/ChartLegend'
import { useChartLegend } from '../../components/Legend/useChartLegend'
import { ChartErrorBoundary } from '../../core/ChartErrorBoundary'
import type {
    ChartConfig,
    ChartLegendConfig,
    ChartMargins,
    ChartTheme,
    LineChartConfig,
    PointClickData,
    Series,
    TooltipContext,
    ValueDomain,
} from '../../core/types'
import { DefaultTooltip } from '../../overlays/DefaultTooltip'
import { AXIS_LABEL_FONT, FONT_FAMILY, measureLabelWidth } from '../../utils/text-measure'
import { LineChart } from '../LineChart/LineChart'
import {
    defaultDeltaFormatter,
    defaultValueFormatter,
    slopeEnd,
    slopeLabelVisible,
    slopeStart,
    sortSlopeTooltipRows,
    type SlopeSeriesMeta,
} from './slope-data'
import { slopeLegendItems } from './slope-legend'
import { SlopeSeriesLabels } from './SlopeSeriesLabels'
import { SlopeValueLabels } from './SlopeValueLabels'

export type { SlopeSeriesMeta } from './slope-data'

const LABEL_FONT = `600 12px ${FONT_FAMILY}`
const VALUE_GAP = 8
const NAME_GAP = 8
const EDGE_PAD = 8
const DEFAULT_POINT_RADIUS = 4

/** Slope-chart legend config. Same shape as every chart's {@link ChartLegendConfig} — clicking a
 *  row toggles that series (interactive by default). Rows carry the per-series change. */
export type SlopeChartLegendConfig = ChartLegendConfig

export interface SlopeChartConfig extends ChartConfig {
    /** Show the series name labels beside each series' last point. Default true. */
    showSeriesLabels?: boolean
    /** Default for the start (left) value labels; per-series `meta.showStartLabel` overrides. Default true. */
    showStartLabels?: boolean
    /** Default for the end (right) value labels; per-series `meta.showEndLabel` overrides. Default true. */
    showEndLabels?: boolean
    /** Legend visibility + placement. Hidden by default. */
    legend?: SlopeChartLegendConfig
    /** Formats the start/end value labels. Defaults to `toLocaleString`. */
    valueFormatter?: (value: number) => string
    /** Formats the per-series change shown in the legend. Defaults to a signed `toLocaleString`. */
    deltaFormatter?: (delta: number) => string
    /** Radius of the point markers in px. Default 4. */
    pointRadius?: number
    /** Value-axis domain control — omit for data-derived auto-scaling. */
    valueDomain?: ValueDomain
}

export interface SlopeChartProps<Meta = SlopeSeriesMeta> {
    series: Series<Meta>[]
    labels: string[]
    config?: SlopeChartConfig
    theme: ChartTheme
    tooltip?: (ctx: TooltipContext<Meta>) => React.ReactNode
    onPointClick?: (data: PointClickData<Meta>) => void
    className?: string
    /** `data-attr` applied to the chart wrapper. See `ChartProps.dataAttr`. */
    dataAttr?: string
    children?: React.ReactNode
    onError?: (error: Error, info: React.ErrorInfo) => void
}

export function SlopeChart<Meta = SlopeSeriesMeta>({ onError, ...rest }: SlopeChartProps<Meta>): React.ReactElement {
    return (
        <ChartErrorBoundary onError={onError}>
            <SlopeChartInner {...rest} />
        </ChartErrorBoundary>
    )
}

function maxLabelWidth(texts: string[]): number {
    return texts.reduce((max, t) => Math.max(max, measureLabelWidth(t, LABEL_FONT)), 0)
}

function SlopeChartInner<Meta = SlopeSeriesMeta>({
    series,
    labels,
    config,
    theme,
    tooltip,
    onPointClick,
    className,
    dataAttr,
    children,
}: SlopeChartProps<Meta>): React.ReactElement {
    const {
        showSeriesLabels = true,
        showStartLabels = true,
        showEndLabels = true,
        legend,
        valueFormatter = defaultValueFormatter,
        deltaFormatter = defaultDeltaFormatter,
        pointRadius = DEFAULT_POINT_RADIUS,
        valueDomain,
    } = config ?? {}

    const showsStart = useCallback(
        (s: Series<Meta>): boolean => slopeLabelVisible(s, 'start', showStartLabels),
        [showStartLabels]
    )
    const showsEnd = useCallback(
        (s: Series<Meta>): boolean => slopeLabelVisible(s, 'end', showEndLabels),
        [showEndLabels]
    )

    // Legend rows come from the full series (so toggled-off ones stay listed and restorable);
    // `visibleSeries` carries the toggled-off entries as excluded for everything the chart draws.
    const legendItems = useMemo(() => slopeLegendItems(series, theme, deltaFormatter), [series, theme, deltaFormatter])
    const { visibleSeries, legendProps } = useChartLegend(series, theme, legend, legendItems)

    // A slope plots only its two ends, so reduce any-length labels to [first, last] to match — this
    // lets a caller hand over a full time-series (data + labels) and have the chart slope it, so the
    // first/last reduction lives here once rather than in every caller.
    const slopeLabels = useMemo(() => (labels.length > 2 ? [labels[0], labels[labels.length - 1]] : labels), [labels])

    // Reserve left/right gutters for the value/name labels, which sit in the margins beyond the plot.
    const { margins, nameOffsetX } = useMemo(() => {
        const startWidth = maxLabelWidth(visibleSeries.filter(showsStart).map((s) => valueFormatter(slopeStart(s))))
        const endWidth = maxLabelWidth(visibleSeries.filter(showsEnd).map((s) => valueFormatter(slopeEnd(s))))
        const nameWidth = showSeriesLabels
            ? maxLabelWidth(
                  visibleSeries
                      .filter((s) => !s.visibility?.excluded && s.visibility?.valueLabel !== false)
                      .map((s) => s.label)
              )
            : 0

        // The x-axis labels sit centred under the two points, so half of the first/last label
        // overhangs the side gutter — reserve room for it too, else a wide label (e.g. a date) clips.
        const firstAxisHalf = slopeLabels.length > 0 ? measureLabelWidth(slopeLabels[0], AXIS_LABEL_FONT) / 2 : 0
        const lastAxisHalf =
            slopeLabels.length > 1 ? measureLabelWidth(slopeLabels[slopeLabels.length - 1], AXIS_LABEL_FONT) / 2 : 0

        const left = Math.max(startWidth > 0 ? startWidth + VALUE_GAP + EDGE_PAD : EDGE_PAD, firstAxisHalf + EDGE_PAD)
        const endGutter = endWidth > 0 ? VALUE_GAP + endWidth : 0
        const nameGutter = nameWidth > 0 ? NAME_GAP + nameWidth : 0
        const right = Math.max(
            endGutter || nameGutter ? endGutter + nameGutter + EDGE_PAD : EDGE_PAD,
            lastAxisHalf + EDGE_PAD
        )

        // Names start just past the end value column.
        const offset = (endWidth > 0 ? VALUE_GAP + endWidth : 0) + NAME_GAP

        const base: Partial<ChartMargins> = { left, right }
        return {
            margins: { ...base, ...config?.margins },
            nameOffsetX: offset,
        }
    }, [visibleSeries, slopeLabels, showsStart, showsEnd, showSeriesLabels, valueFormatter, config?.margins])

    // When the last point is the current incomplete period, dash only the *second half* of the
    // connector so it reads as "the end is provisional", not the whole comparison.
    const dashEnd = useMemo(
        () => visibleSeries.some((s) => (s.meta as SlopeSeriesMeta | undefined)?.incompleteEnd),
        [visibleSeries]
    )

    // A slope is a two-point line — collapse each series to its two points, with a dot at each. A
    // dashed end splits the single segment at its midpoint (renderer-side, no phantom point).
    const slopeSeries = useMemo<Series<Meta>[]>(
        () =>
            visibleSeries.map((s) => ({
                ...s,
                data: [slopeStart(s), slopeEnd(s)],
                points: { ...s.points, radius: pointRadius },
                ...(dashEnd
                    ? {
                          stroke: {
                              ...s.stroke,
                              partial: {
                                  ...s.stroke?.partial,
                                  fromFraction: 0.5,
                              },
                          },
                      }
                    : {}),
            })),
        [visibleSeries, pointRadius, dashEnd]
    )

    // SlopeChart owns the legend (wrapper below); strip it from the inner LineChart's config so the
    // line chart's own built-in legend stays off and we don't render two.
    const lineConfig = useMemo<LineChartConfig>(
        () => ({
            ...config,
            legend: undefined,
            hideYAxis: config?.hideYAxis ?? true,
            showGrid: false,
            margins,
            valueDomain,
        }),
        [config, margins, valueDomain]
    )

    // A caller-supplied tooltip takes precedence; otherwise sort the default rows (see helper) and
    // format values with the chart's valueFormatter so the tooltip matches the on-chart labels' units.
    const sortedTooltip = useCallback(
        (ctx: TooltipContext<Meta>): React.ReactNode => (
            <DefaultTooltip
                {...ctx}
                seriesData={sortSlopeTooltipRows(ctx.seriesData)}
                valueFormatter={valueFormatter}
            />
        ),
        [valueFormatter]
    )

    return (
        <ChartLegend {...legendProps} legendDataAttr="hog-chart-slope-legend">
            <LineChart<Meta>
                series={slopeSeries}
                labels={slopeLabels}
                config={lineConfig}
                theme={theme}
                tooltip={tooltip ?? sortedTooltip}
                onPointClick={onPointClick}
                className={className}
                dataAttr={dataAttr}
            >
                <SlopeValueLabels
                    valueFormatter={valueFormatter}
                    showStartLabels={showStartLabels}
                    showEndLabels={showEndLabels}
                />
                <SlopeSeriesLabels show={showSeriesLabels} offsetX={nameOffsetX} />
                {children}
            </LineChart>
        </ChartLegend>
    )
}
