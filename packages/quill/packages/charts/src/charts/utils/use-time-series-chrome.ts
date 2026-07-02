import { useMemo } from 'react'

import { useChartLegend, type ChartLegendRenderProps } from '../../components/Legend/useChartLegend'
import type { ChartLegendConfig, ChartTheme, Series, ValueDomain } from '../../core/types'
import type { ReferenceLineProps } from '../../overlays/ReferenceLine'
import type { ValueLabelFormatter } from '../../overlays/ValueLabels'
import { buildGoalLineReferenceLines, goalLineValueDomain, type GoalLineConfig } from '../../utils/goal-lines'
import {
    useXTickFormatter,
    useYTickFormatter,
    type XAxisConfig,
    type YAxisConfig,
} from '../../utils/use-axis-formatters'
import { resolveValueLabelsConfig, useSeriesWithValueLabelAllowlist, type ValueLabelsConfig } from './use-value-labels'

export interface TimeSeriesChromeConfig {
    xAxis?: XAxisConfig
    /** The primary y-axis config — drives the default y-tick and value-label formatters. */
    yAxis?: YAxisConfig
    valueLabels?: boolean | ValueLabelsConfig
    legend?: ChartLegendConfig
}

export interface TimeSeriesChrome<Meta> {
    xTickFormatter: ((value: string, index: number) => string | null) | undefined
    yTickFormatter: ((value: number) => string) | undefined
    /** Spread onto the wrapping `<ChartLegend>`. */
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
}

/** The shared chrome preamble of the TimeSeries* wrappers — date-aware x ticks, y ticks, the
 *  built-in click-to-toggle legend, and value-label config — kept in one place so the line/bar/
 *  combo wrappers can't drift. Legend toggling works off the raw `series` so the legend lists the
 *  user's series (not derived trend lines / CI bands); hidden ones flow onward already excluded.
 *  Chart-specific concerns (scales, layouts, derived series, goal-line resolution) stay in each
 *  wrapper. */
export function useTimeSeriesChrome<Meta>(
    series: Series<Meta>[],
    labels: string[],
    theme: ChartTheme,
    config: TimeSeriesChromeConfig
): TimeSeriesChrome<Meta> {
    const { xAxis, yAxis, valueLabels, legend } = config
    const xTickFormatter = useXTickFormatter(xAxis, labels)
    const yTickFormatter = useYTickFormatter(yAxis)
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
    }
}

/** Goal lines resolved against the series they should scale with — the drawn (post-derived)
 *  series for the line chart, the chrome series for bar/combo. `valueDomain` extends the value
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
