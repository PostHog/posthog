import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { useEffect, useState } from 'react'

import { ErrorBoundary } from '~/layout/ErrorBoundary'
import { DataNode } from '~/queries/nodes/DataNode/DataNode'
import { DataTable } from '~/queries/nodes/DataTable/DataTable'
import { InsightViz } from '~/queries/nodes/InsightViz/InsightViz'
import { WebOverview } from '~/queries/nodes/WebOverview/WebOverview'
import { QueryEditor } from '~/queries/QueryEditor/QueryEditor'
import { AnyResponseType, Node, QuerySchema } from '~/queries/schema'
import { QueryContext } from '~/queries/types'

import { DataTableVisualization } from '../nodes/DataVisualization/DataVisualization'
import { SavedInsight } from '../nodes/SavedInsight/SavedInsight'
import { TimeToSeeData } from '../nodes/TimeToSeeData/TimeToSeeData'
import {
    isDataNode,
    isDataTableNode,
    isDataVisualizationNode,
    isInsightVizNode,
    isSavedInsightNode,
    isTimeToSeeDataSessionsNode,
    isWebOverviewQuery,
} from '../utils'

export interface QueryProps<T extends Node = QuerySchema | Node> {
    /** An optional key to identify the query */
    uniqueKey?: string | number
    /** The query to render */
    query: T | string | null
    /** Set this if you're controlling the query parameter */
    setQuery?: (query: T) => void

    /** Custom components passed down to a few query nodes (e.g. custom table columns) */
    context?: QueryContext
    /* Cached Results are provided when shared or exported,
    the data node logic becomes read only implicitly */
    cachedResults?: AnyResponseType
    /** Disable any changes to the query */
    readOnly?: boolean
}

export function Query(props: QueryProps): JSX.Element | null {
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
    if (isDataTableNode(query)) {
        component = (
            <DataTable
                query={query}
                setQuery={setQuery}
                context={queryContext}
                cachedResults={props.cachedResults}
                uniqueKey={props.uniqueKey}
            />
        )
    } else if (isDataVisualizationNode(query)) {
        component = (
            <DataTableVisualization
                query={query}
                setQuery={setQuery}
                cachedResults={props.cachedResults}
                uniqueKey={props.uniqueKey}
                context={queryContext}
            />
        )
    } else if (isDataNode(query)) {
        component = <DataNode query={query} cachedResults={props.cachedResults} />
    } else if (isSavedInsightNode(query)) {
        component = <SavedInsight query={query} context={queryContext} />
    } else if (isInsightVizNode(query)) {
        component = (
            <InsightViz
                query={query}
                setQuery={setQuery}
                context={queryContext}
                readOnly={readOnly}
                uniqueKey={props.uniqueKey}
            />
        )
    } else if (isTimeToSeeDataSessionsNode(query)) {
        component = <TimeToSeeData query={query} cachedResults={props.cachedResults} />
    } else if (isWebOverviewQuery(query)) {
        component = <WebOverview query={query} cachedResults={props.cachedResults} context={queryContext} />
    }

    if (component) {
        return (
            <ErrorBoundary>
                <>
                    {props.context?.showQueryEditor ? (
                        <>
                            <QueryEditor
                                query={JSON.stringify(query)}
                                setQuery={(stringQuery) => setQuery?.(JSON.parse(stringQuery))}
                                context={queryContext}
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
