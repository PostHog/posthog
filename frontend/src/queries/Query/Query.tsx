import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { useEffect, useState } from 'react'
import { HogDebug } from 'scenes/debug/HogDebug'

import { ErrorBoundary } from '~/layout/ErrorBoundary'
import { DataNode } from '~/queries/nodes/DataNode/DataNode'
import { DataTable } from '~/queries/nodes/DataTable/DataTable'
import { InsightViz, insightVizDataNodeKey } from '~/queries/nodes/InsightViz/InsightViz'
import { WebOverview } from '~/queries/nodes/WebOverview/WebOverview'
import { QueryEditor } from '~/queries/QueryEditor/QueryEditor'
import { AnyResponseType, DataTableNode, DataVisualizationNode, InsightVizNode, Node } from '~/queries/schema'
import { QueryContext } from '~/queries/types'

import { DataTableVisualization } from '../nodes/DataVisualization/DataVisualization'
import { SavedInsight } from '../nodes/SavedInsight/SavedInsight'
import {
    isDataTableNode,
    isDataVisualizationNode,
    isHogQuery,
    isInsightVizNode,
    isSavedInsightNode,
    isWebOverviewQuery,
} from '../utils'

export interface QueryProps<Q extends Node> {
    /** An optional key to identify the query */
    uniqueKey?: string | number
    /** The query to render */
    query: Q | string | null
    /** Set this if you're controlling the query parameter */
    setQuery?: (query: Q, isSourceUpdate?: boolean) => void

    /** Custom components passed down to a few query nodes (e.g. custom table columns) */
    context?: QueryContext<any>
    /* Cached Results are provided when shared or exported,
    the data node logic becomes read only implicitly */
    cachedResults?: AnyResponseType
    /** Disable any changes to the query */
    readOnly?: boolean
    /** Reduce UI elements to only show data */
    embedded?: boolean
    /** Disables modals and other things */
    inSharedMode?: boolean
}

export function Query<Q extends Node>(props: QueryProps<Q>): JSX.Element | null {
    const { query: propsQuery, setQuery: propsSetQuery, readOnly, embedded, inSharedMode } = props

    const [localQuery, localSetQuery] = useState(propsQuery)
    useEffect(() => {
        if (propsQuery !== localQuery) {
            localSetQuery(propsQuery)
        }
    }, [propsQuery])

    const query = readOnly ? propsQuery : localQuery
    const setQuery = readOnly ? undefined : propsSetQuery ?? localSetQuery

    const queryContext = props.context || {}

    const uniqueKey =
        props.uniqueKey ?? (props.context?.insightProps && insightVizDataNodeKey(props.context.insightProps))

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
                setQuery={setQuery as ((query: DataTableNode) => void) | undefined}
                context={queryContext}
                cachedResults={props.cachedResults}
                uniqueKey={uniqueKey}
            />
        )
    } else if (isDataVisualizationNode(query)) {
        component = (
            <DataTableVisualization
                query={query}
                setQuery={setQuery as ((query: DataVisualizationNode) => void) | undefined}
                cachedResults={props.cachedResults}
                uniqueKey={uniqueKey}
                context={queryContext}
                readOnly={readOnly}
            />
        )
    } else if (isSavedInsightNode(query)) {
        component = <SavedInsight query={query} context={queryContext} />
    } else if (isInsightVizNode(query)) {
        component = (
            <InsightViz
                query={query}
                setQuery={setQuery as ((query: InsightVizNode) => void) | undefined}
                context={queryContext}
                readOnly={readOnly}
                uniqueKey={uniqueKey}
                embedded={embedded}
                inSharedMode={inSharedMode}
            />
        )
    } else if (isWebOverviewQuery(query)) {
        component = <WebOverview query={query} cachedResults={props.cachedResults} context={queryContext} />
    } else if (isHogQuery(query)) {
        component = (
            <HogDebug
                query={query}
                setQuery={setQuery as undefined | ((query: any) => void)}
                queryKey={String(uniqueKey)}
            />
        )
    } else {
        component = <DataNode query={query} cachedResults={props.cachedResults} />
    }

    if (component) {
        return (
            <ErrorBoundary>
                <>
                    {props.context?.showQueryEditor ? (
                        <>
                            <QueryEditor
                                query={JSON.stringify(query)}
                                setQuery={(stringQuery) => setQuery?.(JSON.parse(stringQuery), true)}
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
