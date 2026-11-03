import { BuiltLogic, LogicWrapper } from 'kea'
import { ReactNode, Suspense, useEffect, useState } from 'react'

import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { ChunkLoadErrorBoundary } from 'scenes/ChunkLoadErrorBoundary'

import { ErrorBoundary } from '~/layout/ErrorBoundary'
import { DataNode } from '~/queries/nodes/DataNode/DataNode'
import { DataTable } from '~/queries/nodes/DataTable/DataTable'
import { insightVizDataNodeKey } from '~/queries/nodes/InsightViz/insightVizKeys'
import {
    isDataTableNode,
    isDataVisualizationNode,
    isInsightVizNode,
    isMetricsQuery,
    isWebOverviewQuery,
} from '~/queries/schema/node-guards'
import {
    AnyResponseType,
    DashboardFilter,
    DataTableNode,
    VisualizationNode,
    HogQLVariable,
    InsightVizNode,
    MetricsQuery,
    Node,
} from '~/queries/schema/schema-general'
import { QueryContext } from '~/queries/types'

import {
    isEndpointsUsageOverviewQuery,
    isEndpointsUsageTrendsQuery,
    isHogQuery,
    isMarketingAnalyticsAggregatedQuery,
    isMetricsHistogramQuery,
    isSavedInsightNode,
    isWebVitalsPathBreakdownQuery,
    isWebVitalsQuery,
} from '../utils'
import {
    DataVisualizationRenderer,
    EndpointsUsageOverviewRenderer,
    EndpointsUsageTrendsRenderer,
    HogDebugRenderer,
    InsightVizRenderer,
    MarketingAnalyticsOverviewRenderer,
    MetricsHistogramQueryRenderer,
    MetricsQueryRenderer,
    QueryEditorRenderer,
    SavedInsightRenderer,
    WebOverviewRenderer,
    WebVitalsPathBreakdownRenderer,
    WebVitalsRenderer,
} from './queryNodeRenderers'

// The fallback fills the slot the renderer will fill, so the page does not jump when the chunk arrives.
const CHART_FALLBACK = 'h-full min-h-80'
const TILE_ROW_FALLBACK = 'h-24'

function LazyQueryNode({
    fallbackClassName,
    children,
}: {
    fallbackClassName: string
    children: ReactNode
}): JSX.Element {
    return (
        <ChunkLoadErrorBoundary>
            {/* The image exporter waits for every .Spinner to detach, so a Spinner fallback stops it capturing the page before this chunk loads. */}
            <Suspense
                fallback={
                    <div className={`flex w-full items-center justify-center ${fallbackClassName}`}>
                        <Spinner className="text-3xl" />
                    </div>
                }
            >
                {children}
            </Suspense>
        </ChunkLoadErrorBoundary>
    )
}

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
    /** Can you edit the insight */
    editMode?: boolean
    /** Dashboard filters to override the ones in the query */
    filtersOverride?: DashboardFilter | null
    /** Dashboard variables to override the ones in the query */
    variablesOverride?: Record<string, HogQLVariable> | null
    /** Passed down if implemented by the query type to e.g. set data attr on a LemonTable in a data table */
    dataAttr?: string
    /** Attach ourselves to another logic, such as the scene logic */
    attachTo?: BuiltLogic | LogicWrapper
}

export function Query<Q extends Node>(props: QueryProps<Q>): JSX.Element | null {
    const {
        query: propsQuery,
        setQuery: propsSetQuery,
        readOnly,
        embedded,
        filtersOverride,
        variablesOverride,
        inSharedMode,
        dataAttr,
        editMode,
    } = props

    const [localQuery, localSetQuery] = useState(propsQuery)
    useEffect(() => {
        if (propsQuery !== localQuery) {
            localSetQuery(propsQuery)
        }
    }, [propsQuery]) // oxlint-disable-line react-hooks/exhaustive-deps

    const query = readOnly || propsSetQuery ? propsQuery : localQuery
    const setQuery = propsSetQuery ?? localSetQuery

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

    let component: JSX.Element
    if (isDataTableNode(query)) {
        component = (
            <DataTable
                attachTo={props.attachTo}
                key={props.uniqueKey}
                query={query}
                setQuery={setQuery as unknown as (query: DataTableNode) => void}
                context={queryContext}
                cachedResults={props.cachedResults}
                uniqueKey={uniqueKey}
                readOnly={readOnly}
                dataAttr={dataAttr}
            />
        )
    } else if (isDataVisualizationNode(query)) {
        component = (
            <LazyQueryNode fallbackClassName={CHART_FALLBACK}>
                <DataVisualizationRenderer.Component
                    attachTo={props.attachTo}
                    query={query}
                    setQuery={setQuery as unknown as (query: VisualizationNode) => void}
                    cachedResults={props.cachedResults}
                    uniqueKey={uniqueKey}
                    context={queryContext}
                    readOnly={readOnly}
                    embedded={embedded}
                    inSharedMode={inSharedMode}
                    editMode={!!editMode}
                    filtersOverride={filtersOverride}
                    variablesOverride={props.variablesOverride}
                />
            </LazyQueryNode>
        )
    } else if (isSavedInsightNode(query)) {
        component = (
            <LazyQueryNode fallbackClassName={CHART_FALLBACK}>
                <SavedInsightRenderer.Component
                    attachTo={props.attachTo}
                    query={query}
                    context={queryContext}
                    readOnly={readOnly}
                    editMode={!!editMode}
                    embedded={embedded}
                />
            </LazyQueryNode>
        )
    } else if (isInsightVizNode(query)) {
        component = (
            <LazyQueryNode fallbackClassName={CHART_FALLBACK}>
                <InsightVizRenderer.Component
                    attachTo={props.attachTo}
                    query={query}
                    setQuery={setQuery as unknown as (query: InsightVizNode) => void}
                    context={queryContext}
                    readOnly={readOnly}
                    editMode={!!editMode}
                    uniqueKey={uniqueKey}
                    cachedResults={props.cachedResults}
                    embedded={embedded}
                    inSharedMode={inSharedMode}
                    filtersOverride={filtersOverride}
                    variablesOverride={variablesOverride}
                />
            </LazyQueryNode>
        )
    } else if (isMetricsQuery(query)) {
        component = (
            <LazyQueryNode fallbackClassName={CHART_FALLBACK}>
                <MetricsQueryRenderer.Component
                    attachTo={props.attachTo}
                    query={query}
                    cachedResults={props.cachedResults}
                    context={queryContext}
                    embedded={embedded}
                    editMode={!!editMode && !readOnly}
                    setQuery={setQuery as unknown as (query: MetricsQuery) => void}
                />
            </LazyQueryNode>
        )
    } else if (isMetricsHistogramQuery(query)) {
        component = (
            <LazyQueryNode fallbackClassName={CHART_FALLBACK}>
                <MetricsHistogramQueryRenderer.Component
                    attachTo={props.attachTo}
                    query={query}
                    cachedResults={props.cachedResults}
                    context={queryContext}
                    embedded={embedded}
                />
            </LazyQueryNode>
        )
    } else if (isEndpointsUsageOverviewQuery(query)) {
        component = (
            <LazyQueryNode fallbackClassName={TILE_ROW_FALLBACK}>
                <EndpointsUsageOverviewRenderer.Component
                    attachTo={props.attachTo}
                    query={query}
                    cachedResults={props.cachedResults}
                    context={queryContext}
                />
            </LazyQueryNode>
        )
    } else if (isEndpointsUsageTrendsQuery(query)) {
        component = (
            <LazyQueryNode fallbackClassName={CHART_FALLBACK}>
                <EndpointsUsageTrendsRenderer.Component
                    attachTo={props.attachTo}
                    query={query}
                    cachedResults={props.cachedResults}
                    context={queryContext}
                />
            </LazyQueryNode>
        )
    } else if (isWebOverviewQuery(query)) {
        component = (
            <LazyQueryNode fallbackClassName={TILE_ROW_FALLBACK}>
                <WebOverviewRenderer.Component
                    attachTo={props.attachTo}
                    query={query}
                    cachedResults={props.cachedResults}
                    context={queryContext}
                    uniqueKey={uniqueKey}
                />
            </LazyQueryNode>
        )
    } else if (isMarketingAnalyticsAggregatedQuery(query)) {
        component = (
            <LazyQueryNode fallbackClassName={TILE_ROW_FALLBACK}>
                <MarketingAnalyticsOverviewRenderer.Component
                    attachTo={props.attachTo}
                    query={query}
                    cachedResults={props.cachedResults}
                    context={queryContext}
                    uniqueKey={uniqueKey}
                />
            </LazyQueryNode>
        )
    } else if (isWebVitalsQuery(query)) {
        component = (
            <LazyQueryNode fallbackClassName={CHART_FALLBACK}>
                <WebVitalsRenderer.Component
                    attachTo={props.attachTo}
                    query={query}
                    cachedResults={props.cachedResults}
                    context={queryContext}
                />
            </LazyQueryNode>
        )
    } else if (isWebVitalsPathBreakdownQuery(query)) {
        component = (
            <LazyQueryNode fallbackClassName={CHART_FALLBACK}>
                <WebVitalsPathBreakdownRenderer.Component
                    attachTo={props.attachTo}
                    query={query}
                    cachedResults={props.cachedResults}
                    context={queryContext}
                />
            </LazyQueryNode>
        )
    } else if (isHogQuery(query)) {
        component = (
            <LazyQueryNode fallbackClassName={CHART_FALLBACK}>
                <HogDebugRenderer.Component
                    attachTo={props.attachTo}
                    query={query}
                    setQuery={setQuery as (query: any) => void}
                    queryKey={String(uniqueKey)}
                />
            </LazyQueryNode>
        )
    } else {
        component = <DataNode attachTo={props.attachTo} query={query} cachedResults={props.cachedResults} />
    }

    return (
        <ErrorBoundary>
            <>
                {queryContext.showQueryEditor ? (
                    <>
                        <LazyQueryNode fallbackClassName={CHART_FALLBACK}>
                            <QueryEditorRenderer.Component
                                query={JSON.stringify(query)}
                                setQuery={(stringQuery) => setQuery?.(JSON.parse(stringQuery), true)}
                                context={queryContext}
                            />
                        </LazyQueryNode>
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
