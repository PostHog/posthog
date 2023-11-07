import { InsightLogicProps } from '~/types'
import { ComponentType, HTMLProps } from 'react'
import { DataTableNode } from '~/queries/schema'

/** Pass custom metadata to queries. Used for e.g. custom columns in the DataTable. */
export interface QueryContext {
    /** Column templates for the DataTable */
    columns?: Record<string, QueryContextColumn>
    /** used to override the value in the query */
    showOpenEditorButton?: boolean
    showQueryEditor?: boolean
    /* Adds help and examples to the query editor component */
    showQueryHelp?: boolean
    insightProps?: InsightLogicProps
    emptyStateHeading?: string
    emptyStateDetail?: string
    rowProps?: (record: unknown) => Omit<HTMLProps<HTMLTableRowElement>, 'key'>
}

export type QueryContextColumnTitleComponent = ComponentType<{
    columnName: string
    query: DataTableNode
}>

export type QueryContextColumnComponent = ComponentType<{
    columnName: string
    query: DataTableNode
    record: unknown
    value: unknown
}>

interface QueryContextColumn {
    title?: string
    renderTitle?: QueryContextColumnTitleComponent
    render?: QueryContextColumnComponent
    align?: 'left' | 'right' | 'center' // default is left
}
