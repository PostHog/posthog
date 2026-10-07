import { ChartDisplayType } from '~/types'

import {
    ChartSettings,
    ChartSettingsDisplay,
    ChartSettingsFormatting,
    CompareFilter,
    DatabaseSerializedFieldType,
    DateRange,
    HogQLQuery,
    Node,
    NodeKind,
    TableSettings,
} from './schema-general'
import { non_negative_integer, positive_integer } from './type-utils'

export interface BIVisualizationNode extends Node<never> {
    kind: NodeKind.BIVisualizationNode
    source: HogQLQuery
    config: BIConfig
    display?: ChartDisplayType
    chartSettings?: ChartSettings
    tableSettings?: TableSettings
}

export type BIAggregation = 'count' | 'count_distinct' | 'sum' | 'average' | 'minimum' | 'maximum' | 'custom'

export type BIDateBucket = 'minute' | 'hour' | 'day' | 'week' | 'month' | 'quarter' | 'year'

export type BIQueryLimit = 100 | 1000 | 10000 | 50000

export type BISortDirection = 'asc' | 'desc'

export interface BISort {
    key: string
    direction: BISortDirection
}

export type BIFilterOperator =
    | 'equals'
    | 'not_equals'
    | 'contains'
    | 'in'
    | 'not_in'
    | 'between'
    | 'greater_than'
    | 'less_than'
    | 'last_7_days'
    | 'is_set'
    | 'is_not_set'
    | 'custom'

export interface BIDataSource {
    table: string
    connectionId?: string
}

export interface BIField {
    id: string
    name: string
    expression: string
    type: DatabaseSerializedFieldType
    source: BIDataSource
    dateBucket?: BIDateBucket
}

export interface BIValue {
    field: BIField
    aggregation: BIAggregation
    customExpression?: string
    label?: string
    tableCalculation?: BITableCalculation
    formatting?: ChartSettingsFormatting
    display?: ChartSettingsDisplay
}

export type BITableCalculationType =
    | 'percent_of_total'
    | 'running_total'
    | 'difference'
    | 'percent_change'
    | 'moving_average'
    | 'rank'

export interface BITableCalculation {
    type: BITableCalculationType
    /** Dimension ID to traverse. Unset chooses the date dimension; 'table' traverses all dimensions. */
    computeUsing?: string
    /** Number of points, including the current point, in a trailing moving average. */
    window?: positive_integer
}

export interface BITopN {
    fieldId: string
    count: positive_integer
    measureIndex: non_negative_integer
    includeOther: boolean
}

export interface BITotals {
    rows?: boolean
    columns?: boolean
    subtotals?: boolean
}

export interface BIFilter {
    field: BIField
    operator: BIFilterOperator
    value: string
    customExpression?: string
    values?: string[]
    valueTo?: string
    enabled?: boolean
}

export interface BIConfig {
    source: BIDataSource | null
    /** Column that receives the worksheet and dashboard date range. */
    dateField?: BIField | null
    dateRange?: DateRange
    compareFilter?: CompareFilter
    chartType: ChartDisplayType
    rows: BIField[]
    columns: BIField[]
    values: BIValue[]
    filters: BIFilter[]
    rowFilterGroup?: BIConditionGroup
    resultFilters?: BIResultFilter[]
    resultFilterGroup?: BIConditionGroup
    limit: BIQueryLimit
    /** null sorts automatically: newest date or highest value first, so top rows survive the LIMIT. */
    sort?: BISort | null
    topN?: BITopN
    totals?: BITotals
}

export interface BIConditionGroup {
    operator: 'AND' | 'OR'
    filters: string[]
    groups: BIConditionGroup[]
}

export interface BIResultFilter {
    id: string
    measureIndex: non_negative_integer
    operator:
        | 'equals'
        | 'not_equals'
        | 'greater_than'
        | 'less_than'
        | 'greater_than_or_equal'
        | 'less_than_or_equal'
        | 'between'
        | 'is_set'
        | 'is_not_set'
    value: string
    valueTo?: string
    enabled?: boolean
}
