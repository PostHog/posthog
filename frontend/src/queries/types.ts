import { ComponentType, HTMLProps } from 'react'

import { QueryFeature } from '~/queries/nodes/DataTable/queryFeatures'
import { DataTableNode, InsightVizNode } from '~/queries/schema'
import { ChartDisplayType, GraphPointPayload, InsightLogicProps, TrendResult } from '~/types'

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
    /** chart-specific rendering context **/
    chartRenderingMetadata?: ChartRenderingMetadata
    /** Whether queries should always be refreshed. */
    alwaysRefresh?: boolean
    /** Extra source feature for Data Tables */
    extraDataTableQueryFeatures?: QueryFeature[]
}

/** Pass custom rendering metadata to specific kinds of charts **/
export interface ChartRenderingMetadata {
    [ChartDisplayType.WorldMap]?: {
        countryProps?: (countryCode: string, countryData: TrendResult | undefined) => Omit<HTMLProps<SVGElement>, 'key'>
    }
    [ChartDisplayType.ActionsPie]?: {
        onSegmentClick?: (payload: GraphPointPayload) => void
    }
}

export type QueryContextColumnTitleComponent = ComponentType<{
    columnName: string
    query: DataTableNode
}>

export type QueryContextColumnComponent = ComponentType<{
    columnName: string
    query: DataTableNode
    record: unknown
    recordIndex: number
    value: unknown
}>

interface QueryContextColumn {
    title?: string
    renderTitle?: QueryContextColumnTitleComponent
    render?: QueryContextColumnComponent
    align?: 'left' | 'right' | 'center' // default is left
    width?: string
}
