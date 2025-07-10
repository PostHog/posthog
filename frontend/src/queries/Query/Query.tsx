import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import {
    RevenueAnalyticsCustomerCountNode,
    RevenueAnalyticsGrowthRateNode,
    RevenueAnalyticsOverviewNode,
    RevenueAnalyticsRevenueNode,
    RevenueAnalyticsTopCustomersNode,
} from 'products/revenue_analytics/frontend/nodes'
import { useEffect, useState } from 'react'
import { HogDebug } from 'scenes/debug/HogDebug'
import { WebActiveHoursHeatmap } from 'scenes/web-analytics/WebActiveHoursHeatmap/WebActiveHoursHeatmap'

import { ErrorBoundary } from '~/layout/ErrorBoundary'
import { DataNode } from '~/queries/nodes/DataNode/DataNode'
import { DataTable } from '~/queries/nodes/DataTable/DataTable'
import { InsightViz, insightVizDataNodeKey } from '~/queries/nodes/InsightViz/InsightViz'
import { WebOverview } from '~/queries/nodes/WebOverview/WebOverview'
import { WebVitals } from '~/queries/nodes/WebVitals/WebVitals'
import { QueryEditor } from '~/queries/QueryEditor/QueryEditor'
import {
    AnyResponseType,
    DashboardFilter,
    DataTableNode,
    DataVisualizationNode,
    HogQLVariable,
    InsightVizNode,
    Node,
} from '~/queries/schema/schema-general'
import { QueryContext } from '~/queries/types'

import { DataTableVisualization } from '../nodes/DataVisualization/DataVisualization'
import { SavedInsight } from '../nodes/SavedInsight/SavedInsight'
import { WebVitalsPathBreakdown } from '../nodes/WebVitals/WebVitalsPathBreakdown'
import {
    isCalendarHeatmapQuery,
    isDataTableNode,
    isDataVisualizationNode,
    isHogQuery,
    isInsightVizNode,
    isRevenueAnalyticsCustomerCountQuery,
    isRevenueAnalyticsGrowthRateQuery,
    isRevenueAnalyticsOverviewQuery,
    isRevenueAnalyticsRevenueQuery,
    isRevenueAnalyticsTopCustomersQuery,
    isSavedInsightNode,
    isWebOverviewQuery,
    isWebVitalsPathBreakdownQuery,
    isWebVitalsQuery,
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
    /** Passed down if implemented by the query type to e.g. set data attr on a LemonTable in a data table */
    dataAttr?: string
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
    } = props

    const [localQuery, localSetQuery] = useState(propsQuery)
    useEffect(() => {
        if (propsQuery !== localQuery) {
            localSetQuery(propsQuery)
        }
    }, [propsQuery]) // eslint-disable-line react-hooks/exhaustive-deps

    const query = readOnly ? propsQuery : localQuery
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
            <DataTableVisualization
                query={query}
                setQuery={setQuery as unknown as (query: DataVisualizationNode) => void}
                cachedResults={props.cachedResults}
                uniqueKey={uniqueKey}
                context={queryContext}
                readOnly={readOnly}
                variablesOverride={props.variablesOverride}
            />
        )
    } else if (isSavedInsightNode(query)) {
        component = <SavedInsight query={query} context={queryContext} readOnly={readOnly} embedded={embedded} />
    } else if (isInsightVizNode(query)) {
        component = (
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
    } else if (isRevenueAnalyticsCustomerCountQuery(query)) {
        component = (
            <RevenueAnalyticsCustomerCountNode
                query={query}
                cachedResults={props.cachedResults}
                context={queryContext}
            />
        )
    } else if (isRevenueAnalyticsOverviewQuery(query)) {
        component = (
            <RevenueAnalyticsOverviewNode query={query} cachedResults={props.cachedResults} context={queryContext} />
        )
    } else if (isRevenueAnalyticsRevenueQuery(query)) {
        component = (
            <RevenueAnalyticsRevenueNode query={query} cachedResults={props.cachedResults} context={queryContext} />
        )
    } else if (isRevenueAnalyticsTopCustomersQuery(query)) {
        component = (
            <RevenueAnalyticsTopCustomersNode
                query={query}
                cachedResults={props.cachedResults}
                context={queryContext}
            />
        )
    } else if (isRevenueAnalyticsGrowthRateQuery(query)) {
        component = (
            <RevenueAnalyticsGrowthRateNode query={query} cachedResults={props.cachedResults} context={queryContext} />
        )
    } else if (isWebOverviewQuery(query)) {
        component = <WebOverview query={query} cachedResults={props.cachedResults} context={queryContext} />
    } else if (isWebVitalsQuery(query)) {
        component = <WebVitals query={query} cachedResults={props.cachedResults} context={queryContext} />
    } else if (isWebVitalsPathBreakdownQuery(query)) {
        component = <WebVitalsPathBreakdown query={query} cachedResults={props.cachedResults} context={queryContext} />
    } else if (isHogQuery(query)) {
        component = <HogDebug query={query} setQuery={setQuery as (query: any) => void} queryKey={String(uniqueKey)} />
    } else if (isCalendarHeatmapQuery(query)) {
        component = <WebActiveHoursHeatmap query={query} context={queryContext} cachedResults={props.cachedResults} />
    } else {
        component = <DataNode query={query} cachedResults={props.cachedResults} />
    }

    return (
        <ErrorBoundary>
            <>
                {queryContext.showQueryEditor ? (
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
