import { ComponentType, HTMLProps } from 'react'

import { QueryFeature } from '~/queries/nodes/DataTable/queryFeatures'
import {
    DataTableNode,
    DataVisualizationNode,
    InsightActorsQuery,
    QuerySchema,
    RefreshType,
} from '~/queries/schema/schema-general'
import { InsightLogicProps, TrendResult } from '~/types'
import { ColumnFeature } from './nodes/DataTable/DataTable'

/** Pass custom metadata to queries. Used for e.g. custom columns in the DataTable. */
export interface QueryContext<Q extends QuerySchema = QuerySchema> {
    /** Column templates for the DataTable */
    columns?: Record<string, QueryContextColumn>
    /** used to override the value in the query */
    showOpenEditorButton?: boolean
    showQueryEditor?: boolean
    /* Adds help and examples to the query editor component */
    showQueryHelp?: boolean
    insightProps?: InsightLogicProps<Q>
    emptyStateHeading?: string
    emptyStateDetail?: string | JSX.Element
    renderEmptyStateAsSkeleton?: boolean
    rowProps?: (record: unknown) => Omit<HTMLProps<HTMLTableRowElement>, 'key'>
    /**
     * Displayed in insight tooltip's "Click to view {groupTypeLabel}".
     * Inferred from the query by default, e.g. `people` or `organizations`.
     */
    groupTypeLabel?: string
    /** NOTE: Custom data point click handling is currently only supported for Trends insights. */
    onDataPointClick?: (series: Pick<InsightActorsQuery, 'day' | 'breakdown' | 'compare'>, data: TrendResult) => void
    /** Refresh behaviour for queries. */
    refresh?: RefreshType
    /** Extra source feature for Data Tables */
    extraDataTableQueryFeatures?: QueryFeature[]
    /** Allow customization of file name when exporting */
    fileNameForExport?: string
    /** Whether to format numbers in human friendly format. */
    formatNumbers?: boolean
    /** Custom column features to pass down to the DataTable */
    columnFeatures?: ColumnFeature[]
}

export type QueryContextColumnTitleComponent = ComponentType<{
    columnName: string
    query: DataTableNode | DataVisualizationNode
}>

export type QueryContextColumnComponent = ComponentType<{
    columnName: string
    query: DataTableNode | DataVisualizationNode
    record: unknown
    recordIndex: number
    rowCount: number
    value: unknown
}>

export interface QueryContextColumn {
    title?: JSX.Element | string
    renderTitle?: QueryContextColumnTitleComponent
    render?: QueryContextColumnComponent
    align?: 'left' | 'right' | 'center' // default is left
    width?: string
    hidden?: boolean // don't show this column in the table
    isRowFillFraction?: boolean // if true, this row will be filled with a background color based on the value (from 0 to 1)
}
