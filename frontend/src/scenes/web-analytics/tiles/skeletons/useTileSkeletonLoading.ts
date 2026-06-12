import { useValues } from 'kea'
import { createElement } from 'react'

import { DataNodeLogicProps, dataNodeLogic } from '@posthog/query-frontend/nodes/DataNode/dataNodeLogic'
import {
    insightVizDataCollectionId,
    insightVizDataNodeKey,
} from '@posthog/query-frontend/nodes/InsightViz/insightVizKeys'
import { getCachedResults } from '@posthog/query-frontend/nodes/InsightViz/utils'
import {
    AnyResponseType,
    DashboardFilter,
    DataTableNode,
    HogQLVariable,
    InsightVizNode,
} from '@posthog/query-frontend/schema/schema-general'
import { QueryContext } from '@posthog/query-frontend/types'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { InsightLogicProps } from '~/types'

interface WebAnalyticsTileSkeletonGateProps {
    dataNodeLogicProps: DataNodeLogicProps
    skeleton: JSX.Element
    children: JSX.Element
}

interface WebAnalyticsTileSkeletonLoaderProps {
    dataNodeLogicProps: DataNodeLogicProps
    skeleton: JSX.Element
    children?: JSX.Element
}

interface BuildInsightVizTileDataNodeLogicPropsParams {
    query: InsightVizNode
    insightProps: InsightLogicProps
    cachedResults?: AnyResponseType
    filtersOverride?: DashboardFilter | null
    variablesOverride?: Record<string, HogQLVariable> | null
    limitContext?: QueryContext['limitContext']
}

interface BuildDataTableTileDataNodeLogicPropsParams {
    query: DataTableNode
    insightProps: InsightLogicProps
    context?: QueryContext
    cachedResults?: AnyResponseType
    uniqueKey?: string | number
}

export function buildInsightVizTileDataNodeLogicProps({
    query,
    insightProps,
    cachedResults,
    filtersOverride,
    variablesOverride,
    limitContext,
}: BuildInsightVizTileDataNodeLogicPropsParams): DataNodeLogicProps {
    const dataNodeLogicKey = insightVizDataNodeKey(insightProps)

    return {
        query: query.source,
        key: dataNodeLogicKey,
        cachedResults: cachedResults || getCachedResults(insightProps.cachedInsight, query.source),
        doNotLoad: insightProps.doNotLoad,
        onData: insightProps.onData,
        loadPriority: insightProps.loadPriority,
        dataNodeCollectionId: insightVizDataCollectionId(insightProps, dataNodeLogicKey),
        filtersOverride,
        variablesOverride,
        limitContext,
    }
}

export function buildDataTableTileDataNodeLogicProps({
    query,
    insightProps,
    context,
    cachedResults,
    uniqueKey,
}: BuildDataTableTileDataNodeLogicPropsParams): DataNodeLogicProps {
    const dataNodeLogicKey = insightVizDataNodeKey(insightProps)
    const dataKey = uniqueKey === undefined ? dataNodeLogicKey : `DataNode.${uniqueKey}`

    return {
        query: query.source,
        key: context?.dataNodeLogicKey ?? dataNodeLogicKey,
        cachedResults,
        dataNodeCollectionId: context?.insightProps?.dataNodeCollectionId || dataKey,
        refresh: context?.refresh,
        maxPaginationLimit: context?.dataTableMaxPaginationLimit,
        limitContext: context?.limitContext,
    }
}

export function WebAnalyticsTileSkeletonGate({
    dataNodeLogicProps,
    skeleton,
    children,
}: WebAnalyticsTileSkeletonGateProps): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)

    if (!featureFlags[FEATURE_FLAGS.WEB_ANALYTICS_TILE_SKELETONS]) {
        return children
    }

    return createElement(WebAnalyticsTileSkeletonLoader, { dataNodeLogicProps, skeleton }, children)
}

function WebAnalyticsTileSkeletonLoader({
    dataNodeLogicProps,
    skeleton,
    children,
}: WebAnalyticsTileSkeletonLoaderProps): JSX.Element {
    const { response, responseLoading } = useValues(dataNodeLogic(dataNodeLogicProps))

    return responseLoading && !response ? skeleton : (children ?? skeleton)
}
