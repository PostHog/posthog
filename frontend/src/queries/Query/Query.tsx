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
import { QueryEditor } from '~/queries/QueryEditor/QueryEditor'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'

export interface QueryProps<T extends Node = QuerySchema | Node> {
    /** The query to render */
    query: T | string | null
    /** Set this if you're controlling the query parameter */
    setQuery?: (query: T) => void

    /** Custom components passed down to a few query nodes (e.g. custom table columns) */
    context?: QueryContext
    /* Cached Results are provided when shared or exported,
    the data node logic becomes read only implicitly */
    cachedResults?: AnyResponseType
}

export function Query(props: QueryProps): JSX.Element | null {
    const { query: propsQuery, setQuery: propsSetQuery } = props
    const readOnly = propsSetQuery === undefined

    const [localQuery, localSetQuery] = useState(propsQuery)
    useEffect(() => {
        if (propsQuery !== localQuery) {
            localSetQuery(propsQuery)
        }
    }, [propsQuery])

    const query = readOnly ? propsQuery : localQuery
    const setQuery = readOnly ? undefined : propsSetQuery ?? localSetQuery

    const queryContext = props.context || {}

    if (query === null) {
        return null
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
        return (
            <ErrorBoundary>
                <>
                    {!!props.context?.showQueryEditor ? (
                        <>
                            <QueryEditor
                                query={JSON.stringify(query)}
                                setQuery={(stringQuery) => setQuery?.(JSON.parse(stringQuery))}
                            />
                            <div className="my-4">
                                <LemonDivider />
                            </div>
                        </>
                    ) : null}
                    {component}
                </>
            </ErrorBoundary>
        )
    }

    return (
        <div className="text-danger border border-danger p-2">
            <strong>PostHoqQuery error:</strong> {query?.kind ? `Invalid node type "${query.kind}"` : 'Invalid query'}
        </div>
    )
}
