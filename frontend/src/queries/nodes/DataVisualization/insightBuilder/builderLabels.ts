import {
    InsightBuilderAggregation,
    InsightBuilderDateGrain,
    InsightBuilderFilterOperator,
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

export const FILTER_OPERATOR_LABELS: Record<InsightBuilderFilterOperator, string> = {
    eq: '=',
    neq: '≠',
    gt: '>',
    gte: '≥',
    lt: '<',
    lte: '≤',
    contains: 'contains',
    not_contains: "doesn't contain",
    is_set: 'is set',
    is_not_set: 'is not set',
}

/** Operators that compare against a value; is_set / is_not_set don't need one */
export function operatorNeedsValue(operator: InsightBuilderFilterOperator): boolean {
    return operator !== 'is_set' && operator !== 'is_not_set'
}

const ORDERED_OPERATORS: InsightBuilderFilterOperator[] = [
    'eq',
    'neq',
    'gt',
    'gte',
    'lt',
    'lte',
    'is_set',
    'is_not_set',
]
const TEXT_OPERATORS: InsightBuilderFilterOperator[] = ['eq', 'neq', 'contains', 'not_contains', 'is_set', 'is_not_set']
const BOOLEAN_OPERATORS: InsightBuilderFilterOperator[] = ['eq', 'neq', 'is_set', 'is_not_set']

/** Operators that make sense for a column's type — numbers/dates get comparisons, text gets contains. */
export function filterOperatorsForField(field?: {
    isNumerical?: boolean
    isDate?: boolean
    typeName?: string
}): InsightBuilderFilterOperator[] {
    if (field?.typeName === 'BOOLEAN') {
        return BOOLEAN_OPERATORS
    }
    if (field?.isDate || field?.isNumerical) {
        return ORDERED_OPERATORS
    }
    return TEXT_OPERATORS
}

export function measureLabel(measure: InsightBuilderMeasure): string {
    if (measure.label) {
        return measure.label
    }
    if (measure.column === '*') {
        return 'Count of rows'
    }
    return `${AGGREGATION_LABELS[measure.aggregation]} of ${measure.column}`
}
