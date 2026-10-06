import { ChartDisplayType } from '~/types'

import {
    ChartSettings,
    DatabaseSerializedFieldType,
    DateRange,
    HogQLQuery,
    Node,
    NodeKind,
    TableSettings,
} from './schema-general'

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
    chartType: ChartDisplayType
    rows: BIField[]
    columns: BIField[]
    values: BIValue[]
    filters: BIFilter[]
    limit: BIQueryLimit
    /** null sorts automatically: newest date or highest value first, so top rows survive the LIMIT. */
    sort?: BISort | null
}
