import { IconGraph, IconLifecycle, IconMagicWand, IconPieChart, IconPulse, IconTrends } from '@posthog/icons'

import { FEATURE_FLAGS } from 'lib/constants'
import { Icon123, IconAreaChart, IconDonutChart, IconHeatmap, IconTableChart } from 'lib/lemon-ui/icons'
import { FeatureFlagsSet } from 'lib/logic/featureFlagLogic'

import { ChartDisplayType } from '~/types'

import { BIAggregation, BIDateBucket, BIFilterOperator, BI_QUERY_LIMITS } from './biEditorTypes'

export const CHART_TYPE_OPTIONS: { value: ChartDisplayType; label: string; icon: JSX.Element }[] = [
    { value: ChartDisplayType.Auto, label: 'Automatic', icon: <IconMagicWand /> },
    { value: ChartDisplayType.ActionsTable, label: 'Table', icon: <IconTableChart /> },
    { value: ChartDisplayType.TwoDimensionalHeatmap, label: 'Pivot table', icon: <IconHeatmap /> },
    { value: ChartDisplayType.BoldNumber, label: 'Big number', icon: <Icon123 /> },
    { value: ChartDisplayType.Metric, label: 'Metric', icon: <IconPulse /> },
    { value: ChartDisplayType.ActionsLineGraph, label: 'Line chart', icon: <IconTrends /> },
    { value: ChartDisplayType.ActionsAreaGraph, label: 'Area chart', icon: <IconAreaChart /> },
    { value: ChartDisplayType.ActionsBar, label: 'Bar chart', icon: <IconGraph /> },
    { value: ChartDisplayType.ActionsStackedBar, label: 'Stacked bar chart', icon: <IconLifecycle /> },
    { value: ChartDisplayType.ActionsPie, label: 'Pie chart', icon: <IconPieChart /> },
    { value: ChartDisplayType.ActionsDonut, label: 'Donut chart', icon: <IconDonutChart /> },
]

export function getChartTypeOptions(featureFlags: FeatureFlagsSet): typeof CHART_TYPE_OPTIONS {
    return CHART_TYPE_OPTIONS.filter(
        (option) => option.value !== ChartDisplayType.Metric || !!featureFlags[FEATURE_FLAGS.METRIC_INSIGHT]
    )
}

export const AGGREGATION_OPTIONS: { value: BIAggregation; label: string }[] = [
    { value: 'sum', label: 'Sum' },
    { value: 'average', label: 'Average' },
    { value: 'minimum', label: 'Minimum' },
    { value: 'maximum', label: 'Maximum' },
    { value: 'count', label: 'Count' },
    { value: 'count_distinct', label: 'Count distinct' },
    { value: 'custom', label: 'SQL expression' },
]

export const NUMERIC_AGGREGATIONS: BIAggregation[] = ['sum', 'average', 'minimum', 'maximum']

export const FILTER_OPERATOR_OPTIONS: { value: BIFilterOperator; label: string }[] = [
    { value: 'in', label: 'Is any of' },
    { value: 'not_in', label: 'Is none of' },
    { value: 'between', label: 'Between' },
    { value: 'equals', label: 'Equals' },
    { value: 'not_equals', label: 'Does not equal' },
    { value: 'contains', label: 'Contains' },
    { value: 'greater_than', label: 'Greater than' },
    { value: 'less_than', label: 'Less than' },
    { value: 'last_7_days', label: 'Last 7 days' },
    { value: 'is_set', label: 'Is set' },
    { value: 'is_not_set', label: 'Is not set' },
    { value: 'custom', label: 'SQL condition' },
]

export const DATE_BUCKET_OPTIONS: { value: BIDateBucket | null; label: string }[] = [
    { value: null, label: 'Exact date' },
    { value: 'minute', label: 'Minute' },
    { value: 'hour', label: 'Hour' },
    { value: 'day', label: 'Day' },
    { value: 'week', label: 'Week' },
    { value: 'month', label: 'Month' },
    { value: 'quarter', label: 'Quarter' },
    { value: 'year', label: 'Year' },
]

export const LIMIT_OPTIONS = BI_QUERY_LIMITS.map((limit) => ({
    value: limit,
    label: limit === 1000 ? '1k' : limit === 10000 ? '10k' : limit === 50000 ? '50k' : String(limit),
}))
