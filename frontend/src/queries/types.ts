import { ComponentType, HTMLProps } from 'react'

import { QueryFeature } from '~/queries/nodes/DataTable/queryFeatures'
import { DataTableNode, DataVisualizationNode, InsightActorsQuery, InsightVizNode } from '~/queries/schema'
import { InsightLogicProps, TrendResult } from '~/types'

/** Pass custom metadata to queries. Used for e.g. custom columns in the DataTable. */
export interface QueryContext<T = InsightVizNode> {
    /** Column templates for the DataTable */
    columns?: Record<string, QueryContextColumn>
    /** used to override the value in the query */
    showOpenEditorButton?: boolean
    showQueryEditor?: boolean
    /* Adds help and examples to the query editor component */
    showQueryHelp?: boolean
    insightProps?: InsightLogicProps<T>
    emptyStateHeading?: string
    emptyStateDetail?: string
    rowProps?: (record: unknown) => Omit<HTMLProps<HTMLTableRowElement>, 'key'>
    /**
     * Displayed in insight tooltip's "Click to view {groupTypeLabel}".
     * Inferred from the query by default, e.g. `people` or `organizations`.
     */
    groupTypeLabel?: string
    /** NOTE: Custom data point click handling is currently only supported for Trends insights. */
    onDataPointClick?: (series: Pick<InsightActorsQuery, 'day' | 'breakdown' | 'compare'>, data: TrendResult) => void
    /** Whether queries should always be refreshed. */
    alwaysRefresh?: boolean
    /** Extra source feature for Data Tables */
    extraDataTableQueryFeatures?: QueryFeature[]
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
    value: unknown
}>

interface QueryContextColumn {
    title?: JSX.Element | string
    renderTitle?: QueryContextColumnTitleComponent
    render?: QueryContextColumnComponent
    align?: 'left' | 'right' | 'center' // default is left
    width?: string
}
