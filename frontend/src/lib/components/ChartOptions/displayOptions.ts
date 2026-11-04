import { ReactNode } from 'react'

import { DEFAULT_DECIMAL_PLACES } from 'lib/utils/numbers'

import { ResultCustomizationBy } from '~/queries/schema/schema-general'
import { AnnotationScope, RetentionDashboardDisplayType } from '~/types'

import type { ChartOptionChoice } from './ChartOptionSelect'

export type DisplayOptionTabKey = 'general' | 'axes' | 'lines'

export const DISPLAY_OPTION_TABS: readonly { key: DisplayOptionTabKey; label: string }[] = [
    { key: 'general', label: 'General' },
    { key: 'axes', label: 'Axes' },
    { key: 'lines', label: 'Lines' },
]

interface DisplayOptionGroupDefinition {
    key: string
    tab: DisplayOptionTabKey
    title?: string
    tooltip?: string
    dataAttr?: string
}

export const DISPLAY_OPTION_GROUPS = [
    { key: 'display', tab: 'general', dataAttr: 'options-display-section' },
    { key: 'x-axis', tab: 'axes', title: 'X-axis' },
    { key: 'y-axis', tab: 'axes', title: 'Y-axis' },
    { key: 'right-y-axis', tab: 'axes', title: 'Right Y-axis' },
    { key: 'style', tab: 'lines', title: 'Style' },
    { key: 'overlays', tab: 'lines', title: 'Overlays', dataAttr: 'options-overlays-section' },
] as const satisfies readonly DisplayOptionGroupDefinition[]

export type DisplayOptionGroupKey = (typeof DISPLAY_OPTION_GROUPS)[number]['key']

type Choice = ChartOptionChoice<string | number>

interface DisplayOptionDefinitionBase {
    name: string
    label: string
    group: DisplayOptionGroupKey
    info?: string
    // The choices already say what the control is, so the label is only read aloud.
    hideLabel?: boolean
    // The label heads its own section, above a full-width control.
    stacked?: boolean
    // Indented under the option above it, which it refines.
    nested?: boolean
}

export type DisplayOptionDefinition = DisplayOptionDefinitionBase &
    (
        | { control: 'checkbox' }
        | { control: 'number'; min?: number; max?: number; suffix?: string; placeholder?: string }
        | { control: 'text'; placeholder?: string }
        | { control: 'select' | 'toggle'; options?: readonly Choice[] }
        | { control: 'colors' }
        // Options with a bespoke control; each surface renders its own.
        | { control: 'custom' }
    )

const SCALE_OPTIONS = [
    { value: 'linear', label: 'Linear' },
    { value: 'log', label: 'Logarithmic' },
] as const

const ROTATION_OPTIONS = [0, -45, -90, 45, 90].map((value) => ({ value, label: `${value}°` }))

// Every chart display option, in the order the insight Options panel and the SQL editor's Display tab
// show them. Each surface binds the options it supports: when they show, and how they read and save.
export const DISPLAY_OPTIONS = [
    {
        name: 'metricSummary',
        label: 'Headline value',
        group: 'display',
        control: 'select',
        options: [
            { value: 'total', label: 'Total' },
            { value: 'average', label: 'Average' },
            { value: 'latest', label: 'Latest' },
        ],
    },
    { name: 'metricShowChange', label: 'Show change', group: 'display', control: 'checkbox' },
    { name: 'metricChangeColors', label: 'Change colors', nested: true, group: 'display', control: 'colors' },
    { name: 'metricColorByDirection', label: 'Color by trend', group: 'display', control: 'checkbox' },
    { name: 'metricTrendColors', label: 'Trend colors', nested: true, group: 'display', control: 'colors' },
    { name: 'lifecycleStacking', label: 'Stack bars', group: 'display', control: 'checkbox' },
    { name: 'valuesOnSeries', label: 'Show values on series', group: 'display', control: 'checkbox' },
    {
        name: 'valueLabelPosition',
        label: 'Value position',
        group: 'display',
        control: 'select',
        options: [
            { value: 'end', label: 'At the end' },
            { value: 'center', label: 'Inside' },
        ],
    },
    { name: 'valueLabelBackground', label: 'Value background', group: 'display', control: 'checkbox' },
    {
        name: 'valueLabelFontSize',
        label: 'Value font size',
        group: 'display',
        control: 'select',
        options: [8, 10, 12, 14, 16, 20, 24, 32].map((value) => ({ value, label: `${value}px` })),
    },
    {
        name: 'valueLabelRotation',
        label: 'Value rotation',
        group: 'display',
        control: 'select',
        options: ROTATION_OPTIONS,
    },
    { name: 'lifecyclePercentages', label: 'Show percentages on series', group: 'display', control: 'checkbox' },
    { name: 'percentStack', label: 'Show as % of total', group: 'display', control: 'checkbox' },
    { name: 'stackBreakdown', label: 'Stack breakdown values', group: 'display', control: 'checkbox' },
    { name: 'sliceNames', label: 'Show names on slices', group: 'display', control: 'checkbox' },
    {
        name: 'pieSliceContent',
        label: 'Show on slices',
        group: 'display',
        control: 'toggle',
        options: [
            { value: 'labels', label: 'Labels' },
            { value: 'values', label: 'Values' },
            { value: 'none', label: 'Nothing' },
        ],
    },
    {
        name: 'pieValueDisplay',
        label: 'Show values as',
        group: 'display',
        control: 'toggle',
        options: [
            { value: 'absolute', label: 'Absolute' },
            { value: 'percentage', label: 'Percentage' },
        ],
    },
    { name: 'pieTotal', label: 'Show total', group: 'display', control: 'checkbox' },
    { name: 'showTotalRow', label: 'Show total row', group: 'display', control: 'checkbox' },
    { name: 'showNullsAsZero', label: 'Show nulls as zero', group: 'display', control: 'checkbox' },
    {
        name: 'barSpacing',
        label: 'Bar spacing',
        group: 'display',
        control: 'select',
        options: [
            { value: 0, label: 'None' },
            { value: 0.1, label: 'Small' },
            { value: 0.2, label: 'Medium' },
            { value: 0.4, label: 'Large' },
        ],
    },
    {
        name: 'hideIncompleteFunnelPeriods',
        label: 'Hide incomplete periods',
        info: "Hides recent periods whose conversion window hasn't fully elapsed, so the trend isn't dragged down by entrants who still have time to convert.",
        group: 'display',
        control: 'checkbox',
    },
    { name: 'alertAnomalyPoints', label: 'Show alert anomaly points', group: 'display', control: 'custom' },
    { name: 'legend', label: 'Show legend', group: 'display', control: 'checkbox' },
    {
        name: 'legendPosition',
        label: 'Legend position',
        nested: true,
        group: 'display',
        control: 'select',
        options: [
            { value: 'top', label: 'Top' },
            { value: 'bottom', label: 'Bottom' },
            { value: 'left', label: 'Left' },
            { value: 'right', label: 'Right' },
        ],
    },
    {
        name: 'excludeOutliers',
        label: 'Exclude outliers',
        info: 'When on, whiskers stop at 1.5 times the interquartile range, so differences between the quartiles are easier to see. When off, the Y-axis stretches to show every value.',
        group: 'display',
        control: 'checkbox',
    },

    {
        name: 'annotations',
        label: 'Annotations',
        info: 'Annotations are saved on an insight, a dashboard, the project, or the organization. Choose which of those to show here.',
        group: 'display',
        control: 'select',
        options: [
            { value: 'all', label: 'All' },
            { value: 'none', label: 'None' },
            { value: AnnotationScope.Insight, label: 'Insight' },
            { value: AnnotationScope.Dashboard, label: 'Dashboard' },
            { value: AnnotationScope.Project, label: 'Project' },
            { value: AnnotationScope.Organization, label: 'Organization' },
        ],
    },
    { name: 'unit', label: 'Unit', stacked: true, group: 'display', control: 'custom' },
    {
        name: 'resultCustomizationBy',
        label: 'Color customization by',
        info: "You can customize the appearance of individual results in your insights. This can be done based on the result's name (e.g., customize the breakdown value 'pizza' for the first series) or based on the result's rank (e.g., customize the first dataset in the results).",
        stacked: true,
        group: 'display',
        control: 'toggle',
        options: [
            { value: ResultCustomizationBy.Value, label: 'By name' },
            { value: ResultCustomizationBy.Position, label: 'By rank' },
        ],
    },
    {
        name: 'decimalPlaces',
        label: 'Decimal places',
        group: 'display',
        control: 'number',
        min: 0,
        max: 9,
        placeholder: String(DEFAULT_DECIMAL_PLACES),
    },
    {
        name: 'retentionDashboardDisplay',
        label: 'On dashboards',
        stacked: true,
        group: 'display',
        control: 'select',
        options: [
            { value: RetentionDashboardDisplayType.TableOnly, label: 'Show table only' },
            { value: RetentionDashboardDisplayType.GraphOnly, label: 'Show graph only' },
            { value: RetentionDashboardDisplayType.All, label: 'Show both' },
        ],
    },
    {
        name: 'retentionCohortLabelStart',
        label: 'Cohort labels start at',
        info: 'Controls the starting index used to label cohort columns. Display only, does not affect the calculations.',
        stacked: true,
        group: 'display',
        control: 'toggle',
    },

    { name: 'xAxisLabel', label: 'Label', group: 'x-axis', control: 'text', placeholder: 'None' },
    { name: 'xAxisScale', label: 'Scale', hideLabel: true, group: 'x-axis', control: 'toggle', options: SCALE_OPTIONS },
    {
        name: 'xAxisBeginAtZero',
        label: 'Begin at zero',
        info: 'When off, the axis starts just below your lowest value instead of at zero, so small changes are easier to see.',
        group: 'x-axis',
        control: 'checkbox',
    },
    {
        name: 'xAxisDateFormat',
        label: 'Date format',
        info: 'For example, YYYY-MM-DD, MMM YYYY, or DD/MM/YYYY.',
        group: 'x-axis',
        control: 'text',
        placeholder: 'Automatic',
    },
    {
        name: 'xAxisTickRotation',
        label: 'Tick label rotation',
        group: 'x-axis',
        control: 'select',
        // A select value can't be null, so "Automatic" stands in for an unset rotation.
        options: [{ value: 'auto', label: 'Automatic' }, ...ROTATION_OPTIONS],
    },
    { name: 'xAxisShowTicks', label: 'Show tick labels', group: 'x-axis', control: 'checkbox' },
    { name: 'xAxisBorder', label: 'Show border', group: 'x-axis', control: 'checkbox' },

    { name: 'yAxisLabel', label: 'Label', group: 'y-axis', control: 'text', placeholder: 'None' },
    { name: 'yAxisMin', label: 'Minimum', group: 'y-axis', control: 'number', placeholder: 'Auto' },
    { name: 'yAxisMax', label: 'Maximum', group: 'y-axis', control: 'number', placeholder: 'Auto' },
    {
        name: 'yAxisBeginAtZero',
        label: 'Begin at zero',
        info: 'When off, the axis starts just below your lowest value instead of at zero, so small changes are easier to see.',
        group: 'y-axis',
        control: 'checkbox',
    },
    { name: 'multipleYAxes', label: 'Show multiple Y-axes', group: 'y-axis', control: 'checkbox' },
    { name: 'yAxisShowTicks', label: 'Show tick labels', group: 'y-axis', control: 'checkbox' },
    { name: 'yAxisGridLines', label: 'Show grid lines', group: 'y-axis', control: 'checkbox' },
    { name: 'yAxisBorder', label: 'Show border', group: 'y-axis', control: 'checkbox' },
    { name: 'yAxisScale', label: 'Scale', hideLabel: true, group: 'y-axis', control: 'toggle', options: SCALE_OPTIONS },

    { name: 'rightYAxisLabel', label: 'Label', group: 'right-y-axis', control: 'text', placeholder: 'None' },
    {
        name: 'rightYAxisBeginAtZero',
        label: 'Begin at zero',
        info: 'When off, the axis starts just below your lowest value instead of at zero, so small changes are easier to see.',
        group: 'right-y-axis',
        control: 'checkbox',
    },
    { name: 'rightYAxisShowTicks', label: 'Show tick labels', group: 'right-y-axis', control: 'checkbox' },
    { name: 'rightYAxisGridLines', label: 'Show grid lines', group: 'right-y-axis', control: 'checkbox' },
    {
        name: 'rightYAxisScale',
        label: 'Scale',
        hideLabel: true,
        group: 'right-y-axis',
        control: 'toggle',
        options: SCALE_OPTIONS,
    },

    {
        name: 'lineStyle',
        label: 'Line style',
        hideLabel: true,
        group: 'style',
        control: 'toggle',
        options: [
            { value: 'smooth', label: 'Smooth' },
            { value: 'linear', label: 'Straight' },
        ],
    },
    { name: 'smoothing', label: 'Smoothing', hideLabel: true, group: 'style', control: 'select' },
    {
        name: 'retentionSeriesColorMode',
        label: 'Cohort line colors',
        info: 'One shade draws every cohort in the same color, with the newest cohort the most solid.',
        stacked: true,
        group: 'style',
        control: 'toggle',
        options: [
            { value: 'palette', label: 'One per cohort' },
            { value: 'opacity', label: 'One shade' },
        ],
    },

    { name: 'trendLines', label: 'Show trend lines', group: 'overlays', control: 'checkbox' },
    { name: 'movingAverage', label: 'Show moving average', group: 'overlays', control: 'checkbox' },
    {
        name: 'movingAverageIntervals',
        label: 'Intervals',
        info: "The number of data points to use for calculating the moving average. A larger number will create a smoother line but with more lag. You can't use a number greater than the amount of intervals in your date range.",
        nested: true,
        group: 'overlays',
        control: 'number',
        min: 2,
    },
    { name: 'confidenceInterval', label: 'Show confidence intervals', group: 'overlays', control: 'checkbox' },
    {
        name: 'confidenceLevel',
        label: 'Confidence level',
        info: 'A 95% confidence level means that for each data point, we are 95% confident that the true value is within the confidence interval.',
        nested: true,
        group: 'overlays',
        control: 'number',
        min: 0,
        max: 100,
        suffix: '%',
    },
    { name: 'alertThresholdLines', label: 'Show alert threshold lines', group: 'overlays', control: 'checkbox' },
    { name: 'retentionMeanLine', label: 'Show mean line', group: 'overlays', control: 'checkbox' },
] as const satisfies readonly DisplayOptionDefinition[]

type Definitions = (typeof DISPLAY_OPTIONS)[number]
export type DisplayOptionName = Definitions['name']
type DefinitionOf<N extends DisplayOptionName> = Extract<Definitions, { name: N }>

// A number choice saves any number (a stored value may predate today's choices); a string keeps its literals.
type Widen<V> = V extends number ? number : V
type ChoiceValue<D> = D extends { options: readonly { value: infer V }[] } ? Widen<V> : string | number

// What an option reads and saves, from its control: a checkbox is a boolean, a number input may be empty.
export type DisplayOptionValue<N extends DisplayOptionName> =
    DefinitionOf<N> extends { control: 'checkbox' }
        ? boolean
        : DefinitionOf<N> extends { control: 'number' }
          ? number | undefined
          : DefinitionOf<N> extends { control: 'text' }
            ? string | undefined
            : DefinitionOf<N> extends { control: 'select' | 'toggle' }
              ? ChoiceValue<DefinitionOf<N>>
              : DefinitionOf<N> extends { control: 'colors' }
                ? DirectionColors
                : never

export interface DirectionColors {
    increase: string
    decrease: string
}

export interface DisplayOptionBinding<C, V> {
    showCondition: (c: C) => boolean | null | undefined
    value?: (c: C) => V
    onChange?: (value: V, c: C) => void
    // For a `custom` option, which has no generic control.
    render?: (c: C) => ReactNode
    disabledReason?: (c: C) => string | null | undefined
    // A message under the control, such as an inverted range.
    warning?: (c: C) => string | null | undefined
    // Choices that depend on the chart, such as smoothing windows for the current interval.
    options?: (c: C) => ChartOptionChoice<V & (string | number)>[]
    placeholder?: (c: C) => string
    suffix?: (c: C) => string
    // Options set away from their default, summed into the badge on the Options button.
    changedCount?: (c: C) => number | boolean | null | undefined
    dataAttr?: string
}

export type DisplayOptionBindings<C> = {
    [N in DisplayOptionName]?: DisplayOptionBinding<C, DisplayOptionValue<N>>
}

export interface DisplayOptionItem {
    name: DisplayOptionName
    element: ReactNode
}

export interface DisplayOptionSection {
    key: string
    title?: string
    tooltip?: string
    dataAttr?: string
    items: DisplayOptionItem[]
}

export interface DisplayOptionTab {
    key: DisplayOptionTabKey
    label: string
    sections: DisplayOptionSection[]
    count: number
}
