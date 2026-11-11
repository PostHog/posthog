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

export type BICatalogMetricStatus = 'approved' | 'proposed'

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
    label?: string
    expression: string
    type: DatabaseSerializedFieldType
    source: BIDataSource
    dateBucket?: BIDateBucket
    datePart?: 'month' | 'quarter' | 'day_of_week'
    localDefinition?: BILocalFieldDefinition
    localFieldId?: string
}

export type BILocalFieldDefinition =
    | { kind: 'expression'; expression: string; aggregate: boolean }
    | { kind: 'groups'; expression: string; groups: BICategoryGroup[]; other: string; preserveUngrouped?: boolean }
    | { kind: 'bins'; expression: string; width: number; origin: number }

export interface BICategoryGroup {
    name: string
    values: string[]
}

export interface BIHierarchy {
    id: string
    name: string
    /** Ordered from the broadest dimension to the most detailed. */
    levels: BIField[]
}

export interface BIValue {
    field: BIField
    /** Measures in older worksheets belong to rows. */
    shelf?: 'rows' | 'columns'
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
    /** Require a complete window of non-null values before displaying a moving average. */
    requireFullWindow?: boolean
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
    label?: string
    field: BIField
    operator: BIFilterOperator
    value: string
    customExpression?: string
    values?: string[]
    valueTo?: string
    enabled?: boolean
}

export interface BIPaneSettings {
    /** Ordered dimension IDs used to split returned groups into separate charts. */
    fields: string[]
    /** Use a separate value scale for each pane instead of a shared primary scale. */
    independentAxes?: boolean
    /** Calculate reference lines from each pane or from all returned worksheet marks. */
    referenceLines?: 'pane' | 'worksheet'
}

export interface BIConfig {
    source: BIDataSource | null
    /** Executable catalog query snapshot. Dates and grouping belong to the definition, not the shelves. */
    querySnapshot?: HogQLQuery
    /** Catalog provenance only: the snapshot does not track subsequent definition edits. */
    catalogMetric?: string
    /** Catalog metadata at copy time, not a live approval of the worksheet. */
    catalogMetricContext?: {
        id: string
        status: BICatalogMetricStatus
        isDrifted: boolean
        unit: string
        owner: string | null
        updatedAt: string | null
    }
    /** Reusable expressions owned by this worksheet only. */
    localFields?: BIField[]
    /** Named dimension sequences saved with the worksheet; imports are independent copies. */
    hierarchies?: BIHierarchy[]
    hierarchyDrillPath?: {
        hierarchyId: string
        previousField: BIField
        nextField: BIField
        filterIds: string[]
    }[]
    memberAliases?: { field: BIField; aliases: { value: string | null; label: string }[] }[]
    colorBy?: string | null
    /** Split the returned groups into charts using these ordered dimension IDs. */
    panes?: BIPaneSettings
    /** Column that receives the worksheet and dashboard date range. */
    dateField?: BIField | null
    dateRange?: DateRange
    compareFilter?: CompareFilter
    /** Explore only the comparison window, using dateRange as its reference window. */
    comparisonPeriod?: 'previous' | null
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
    /** Fill missing date buckets before table calculations. Unset preserves observed points only. */
    missingDates?: 'gap' | 'zero'
}

export interface BIConditionGroup {
    operator: 'AND' | 'OR'
    filters: string[]
    groups: BIConditionGroup[]
}

export interface BIResultFilter {
    label?: string
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
