import { useMemo } from 'react'

import { useChartLegend, type ChartLegendRenderProps } from '../../components/Legend/useChartLegend'
import type { ChartLegendConfig, ChartTheme, Series, ValueDomain, YAxis } from '../../core/types'
import type { ReferenceLineProps } from '../../overlays/ReferenceLine'
import type { ValueLabelFormatter } from '../../overlays/ValueLabels'
import { buildGoalLineReferenceLines, goalLineValueDomain, type GoalLineConfig } from '../../utils/goal-lines'
import {
    buildYAxes,
    normalizeYAxisList,
    primaryYAxisConfig,
    useXTickFormatter,
    useYTickFormatter,
    type XAxisConfig,
    type YAxisConfig,
} from '../../utils/use-axis-formatters'
import { resolveValueLabelsConfig, useSeriesWithValueLabelAllowlist, type ValueLabelsConfig } from './use-value-labels'

export interface UseTimeSeriesConfig {
    xAxis?: XAxisConfig
    /** Single object for one y-axis; array for multi-axis charts (one entry per axis, `id`
     *  matching `Series.yAxisId`). The primary (left) entry drives the default y-tick and
     *  value-label formatters. */
    yAxis?: YAxisConfig | YAxisConfig[]
    valueLabels?: boolean | ValueLabelsConfig
    legend?: ChartLegendConfig
}

export interface UseTimeSeriesResult<Meta> {
    xTickFormatter: ((value: string, index: number) => string | null) | undefined
    yTickFormatter: ((value: number) => string) | undefined
    legendProps: ChartLegendRenderProps
    /** Series with legend toggling applied (hidden ones excluded) — before the value-label
     *  allowlist. Derived overlays (e.g. trend lines) resolve their sources against this. */
    visibleSeries: Series<Meta>[]
    /** `visibleSeries` with the value-label allowlist applied — what the chart should draw,
     *  or feed into the derived-series pipeline first. */
    chartSeries: Series<Meta>[]
    valueLabelsConfig: ValueLabelsConfig | null
    /** Formatter for the `<ValueLabels>` overlay. Undefined when value labels are off. */
    valueLabelFormatter: ValueLabelFormatter | undefined
    /** The primary (left) axis config — drives the base chart's scalar y fields
     *  (`yScaleType`/`hideYAxis`/`yAxisLabel`/`showGrid`) and the left gutter when a
     *  right-axis series is present. */
    primaryYAxis: YAxisConfig | undefined
    /** Per-axis configs for the base chart, only when the caller passed a `yAxis` array — a
     *  single object keeps the existing single-axis path untouched (no `yAxes` on the config). */
    yAxes: YAxis[] | undefined
}

/** The shared preamble of the TimeSeries* wrappers — date-aware x ticks, y ticks (primary +
 *  multi-axis resolution), the built-in click-to-toggle legend, and value-label config — kept in
 *  one place so the line/bar/combo wrappers can't drift. Legend toggling works off the raw
 *  `series` so the legend lists the user's series (not derived trend lines / CI bands); hidden
 *  ones flow onward already excluded. Chart-specific concerns (scales, layouts, derived series,
 *  goal-line resolution) stay in each wrapper. */
export function useTimeSeries<Meta>(
    series: Series<Meta>[],
    labels: string[],
    theme: ChartTheme,
    config: UseTimeSeriesConfig
): UseTimeSeriesResult<Meta> {
    const { xAxis, yAxis, valueLabels, legend } = config
    const axisList = useMemo(() => normalizeYAxisList(yAxis), [yAxis])
    const primaryYAxis = useMemo(() => primaryYAxisConfig(axisList), [axisList])
    const yAxes = useMemo(() => (Array.isArray(yAxis) ? buildYAxes(axisList) : undefined), [yAxis, axisList])
    const xTickFormatter = useXTickFormatter(xAxis, labels)
    const yTickFormatter = useYTickFormatter(primaryYAxis)
    const { visibleSeries, legendProps } = useChartLegend(series, theme, legend)
    const valueLabelsConfig = resolveValueLabelsConfig(valueLabels)
    const chartSeries = useSeriesWithValueLabelAllowlist(visibleSeries, valueLabelsConfig?.seriesKeys)
    const valueLabelFormatter = valueLabelsConfig ? (valueLabelsConfig.formatter ?? yTickFormatter) : undefined
    return {
        xTickFormatter,
        yTickFormatter,
        legendProps,
        visibleSeries,
        chartSeries,
        valueLabelsConfig,
        valueLabelFormatter,
        primaryYAxis,
        yAxes,
    }
}

/** Goal lines resolved against the series they should scale with — the drawn (post-derived)
 *  series for the line chart, the hook's `chartSeries` for bar/combo. `valueDomain` extends the value
 *  axis to cover goal lines outside the data range, so an off-scale goal still renders on-plot;
 *  both results are referentially stable so they don't re-trigger scale recomputation. */
export function useGoalLines<Meta>(
    goalLines: GoalLineConfig[] | undefined,
    series: Series<Meta>[]
): { referenceLines: ReferenceLineProps[]; valueDomain: ValueDomain | undefined } {
    const referenceLines = useMemo(() => buildGoalLineReferenceLines(goalLines, series), [goalLines, series])
    const valueDomain = useMemo(() => goalLineValueDomain(referenceLines), [referenceLines])
    return { referenceLines, valueDomain }
}
