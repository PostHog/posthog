import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { useEffect, useMemo, useState } from 'react'
import { HogDebug } from 'scenes/debug/HogDebug'

import { ErrorBoundary } from '~/layout/ErrorBoundary'
import { DataNode } from '~/queries/nodes/DataNode/DataNode'
import { DataTable } from '~/queries/nodes/DataTable/DataTable'
import { InsightViz, insightVizDataNodeKey } from '~/queries/nodes/InsightViz/InsightViz'
import { WebOverview } from '~/queries/nodes/WebOverview/WebOverview'
import { QueryEditor } from '~/queries/QueryEditor/QueryEditor'
import {
    AnyResponseType,
    DashboardFilter,
    DataTableNode,
    DataVisualizationNode,
    HogQLVariable,
    InsightVizNode,
    Node,
} from '~/queries/schema'
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
    /** Dashboard filters to override the ones in the query */
    filtersOverride?: DashboardFilter | null
    /** Dashboard variables to override the ones in the query */
    variablesOverride?: Record<string, HogQLVariable> | null
}

export function Query<Q extends Node>(props: QueryProps<Q>): JSX.Element | null {
    const {
        query: propsQuery,
        setQuery: propsSetQuery,
        readOnly,
        embedded,
        filtersOverride,
        variablesOverride,
        cachedResults,
        inSharedMode,
    } = props

    const [localQuery, localSetQuery] = useState(propsQuery)
    useEffect(() => {
        if (propsQuery !== localQuery) {
            localSetQuery(propsQuery)
        }
    }, [propsQuery]) // eslint-disable-line react-hooks/exhaustive-deps

    const query = readOnly ? propsQuery : localQuery
    const setQuery = propsSetQuery ?? localSetQuery

    const queryContext = useMemo(() => props.context || {}, [props.context])

    const uniqueKey =
        props.uniqueKey ?? (props.context?.insightProps && insightVizDataNodeKey(props.context.insightProps))

    const component = useMemo(() => {
        // If the query is null or a string, we don't need to render anything
        // this will be handled below, but `useMemo` must be called unconditionally - React things
        if (query === null || typeof query === 'string') {
            return null
        }

        if (isDataTableNode(query)) {
            return (
                <DataTable
                    query={query}
                    setQuery={setQuery as unknown as (query: DataTableNode) => void}
                    context={queryContext}
                    cachedResults={cachedResults}
                    uniqueKey={uniqueKey}
                    readOnly={readOnly}
                />
            )
        }

        if (isDataVisualizationNode(query)) {
            return (
                <DataTableVisualization
                    query={query}
                    setQuery={setQuery as unknown as (query: DataVisualizationNode) => void}
                    cachedResults={cachedResults}
                    uniqueKey={uniqueKey}
                    context={queryContext}
                    readOnly={readOnly}
                    variablesOverride={variablesOverride}
                />
            )
        }

        if (isSavedInsightNode(query)) {
            return <SavedInsight query={query} context={queryContext} readOnly={readOnly} embedded={embedded} />
        }

        if (isInsightVizNode(query)) {
            return (
                <InsightViz
                    query={query}
                    setQuery={setQuery as unknown as (query: InsightVizNode) => void}
                    context={queryContext}
                    readOnly={readOnly}
                    uniqueKey={uniqueKey}
                    embedded={embedded}
                    inSharedMode={inSharedMode}
                    filtersOverride={filtersOverride}
                    variablesOverride={variablesOverride}
                />
            )
        }

        if (isWebOverviewQuery(query)) {
            return <WebOverview query={query} cachedResults={cachedResults} context={queryContext} />
        }

        if (isHogQuery(query)) {
            return <HogDebug query={query} setQuery={setQuery as (query: any) => void} queryKey={String(uniqueKey)} />
        }

        return <DataNode query={query} cachedResults={cachedResults} />
    }, [
        query,
        queryContext,
        embedded,
        filtersOverride,
        variablesOverride,
        inSharedMode,
        cachedResults,
        readOnly,
        setQuery,
        uniqueKey,
    ])

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
