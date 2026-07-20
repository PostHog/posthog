import {
    InsightBuilderAggregation,
    InsightBuilderDateGrain,
    InsightBuilderMeasure,
} from '~/queries/schema/schema-general'

export const AGGREGATION_LABELS: Record<InsightBuilderAggregation, string> = {
    sum: 'Sum',
    avg: 'Average',
    min: 'Min',
    max: 'Max',
    count: 'Count',
    count_distinct: 'Count distinct',
    median: 'Median',
    p90: '90th percentile',
    p95: '95th percentile',
    p99: '99th percentile',
}

export const NUMERIC_AGGREGATIONS: InsightBuilderAggregation[] = [
    'sum',
    'avg',
    'min',
    'max',
    'count',
    'count_distinct',
    'median',
    'p90',
    'p95',
    'p99',
]

export const NON_NUMERIC_AGGREGATIONS: InsightBuilderAggregation[] = ['count', 'count_distinct', 'min', 'max']

export const DATE_GRAIN_LABELS: Record<InsightBuilderDateGrain, string> = {
    hour: 'Hour',
    day: 'Day',
    week: 'Week',
    month: 'Month',
    quarter: 'Quarter',
    year: 'Year',
}

export const DATE_GRAIN_OPTIONS: InsightBuilderDateGrain[] = ['hour', 'day', 'week', 'month', 'quarter', 'year']

export function measureLabel(measure: InsightBuilderMeasure): string {
    if (measure.label) {
        return measure.label
    }
    if (measure.column === '*') {
        return 'Count of rows'
    }
    return `${AGGREGATION_LABELS[measure.aggregation]} of ${measure.column}`
}
