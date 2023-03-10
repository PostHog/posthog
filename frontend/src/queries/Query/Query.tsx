import {
    isDataNode,
    isDataTableNode,
    isLegacyQuery,
    isInsightQueryNode,
    isInsightVizNode,
    isTimeToSeeDataSessionsNode,
} from '../utils'
import { DataTable } from '~/queries/nodes/DataTable/DataTable'
import { DataNode } from '~/queries/nodes/DataNode/DataNode'
import { InsightViz } from '~/queries/nodes/InsightViz/InsightViz'
import { AnyResponseType, Node, QueryContext, QuerySchema } from '~/queries/schema'
import { ErrorBoundary } from '~/layout/ErrorBoundary'
import { LegacyInsightQuery } from '~/queries/nodes/LegacyInsightQuery/LegacyInsightQuery'
import { InsightQuery } from '~/queries/nodes/InsightQuery/InsightQuery'
import { useEffect, useState } from 'react'
import { TimeToSeeData } from '../nodes/TimeToSeeData/TimeToSeeData'

export interface QueryProps<T extends Node = QuerySchema | Node> {
    /** The query to render */
    query: T | string
    /** Set this if you're controlling the query parameter */
    setQuery?: (query: T) => void
    /** Does not call setQuery, not even locally */
    readOnly?: boolean
    /** Custom components passed down to a few query nodes (e.g. custom table columns) */
    context?: QueryContext
    /* Cached Results are provided when shared or exported,
    the data node logic becomes read only implicitly */
    cachedResults?: AnyResponseType
}

export function Query(props: QueryProps): JSX.Element {
    const { query: propsQuery, setQuery: propsSetQuery, readOnly } = props
    const [localQuery, localSetQuery] = useState(propsQuery)
    useEffect(() => {
        if (propsQuery !== localQuery) {
            localSetQuery(propsQuery)
        }
    }, [propsQuery])

    const query = readOnly ? propsQuery : localQuery
    const setQuery = readOnly ? undefined : propsSetQuery ?? localSetQuery

    const queryContext = props.context || {}
    if (!!props.readOnly) {
        queryContext.readonly = true
    }

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
        component = (
            <DataTable query={query} setQuery={setQuery} context={queryContext} cachedResults={props.cachedResults} />
        )
    } else if (isDataNode(query)) {
        component = <DataNode query={query} cachedResults={props.cachedResults} />
    } else if (isInsightVizNode(query)) {
        component = <InsightViz query={query} setQuery={setQuery} />
    } else if (isInsightQueryNode(query)) {
        component = <InsightQuery query={query} />
    } else if (isTimeToSeeDataSessionsNode(query)) {
        component = <TimeToSeeData query={query} cachedResults={props.cachedResults} />
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
