import { isDataNode, isDataTableNode, isLegacyQuery, isInsightQueryNode } from '../utils'
import { DataTable } from '~/queries/nodes/DataTable/DataTable'
import { DataNode } from '~/queries/nodes/DataNode/DataNode'
import { Node, QueryCustom, QuerySchema } from '~/queries/schema'
import { ErrorBoundary } from '~/layout/ErrorBoundary'
import { LegacyInsightQuery } from '~/queries/nodes/LegacyInsightQuery/LegacyInsightQuery'
import { InsightQuery } from '~/queries/nodes/InsightQuery/InsightQuery'
import { useState } from 'react'

export interface QueryProps<T extends Node = QuerySchema | Node> {
    /** The query to render */
    query: T | string
    /** Set this if the user can update the query */
    setQuery?: (node: T) => void
    /** Can the query can still be edited locally if there is `setQuery` */
    setQueryLocally?: boolean
    /** Custom components passed down to query nodes (e.g. custom table columns) */
    custom?: QueryCustom
}

export function Query(props: QueryProps): JSX.Element {
    const { query: globalQuery, setQuery: globalSetQuery, setQueryLocally, custom } = props
    const [localQuery, localSetQuery] = useState(globalQuery)
    const query = setQueryLocally ? localQuery : globalQuery
    const setQuery = setQueryLocally ? localSetQuery : globalSetQuery

    if (typeof query === 'string') {
        try {
            return <Query {...props} query={JSON.parse(query)} />
        } catch (e: any) {
            return <div className="border border-danger p-4 text-danger">Error parsing JSON: {e.message}</div>
        }
    }
    let component
    if (isLegacyQuery(query)) {
        component = <LegacyInsightQuery query={query} />
    } else if (isDataTableNode(query)) {
        component = <DataTable query={query} setQuery={setQuery} custom={custom} />
    } else if (isDataNode(query)) {
        component = <DataNode query={query} />
    } else if (isInsightQueryNode(query)) {
        component = <InsightQuery query={query} />
    }

    if (component) {
        return <ErrorBoundary>{component}</ErrorBoundary>
    }

    return (
        <div className="text-danger border border-danger p-2">
            <strong>PostHoqQuery error:</strong> {query?.kind ? `Invalid node type "${query.kind}"` : 'Invalid query'}
        </div>
    )
}
