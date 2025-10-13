import { BuiltLogic, LogicWrapper, useValues } from 'kea'
import { useState } from 'react'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { useAttachedLogic } from 'lib/logic/scenes/useAttachedLogic'
import { urls } from 'scenes/urls'

import { OverviewGrid, OverviewItem } from '~/queries/nodes/OverviewGrid/OverviewGrid'
import { AnyResponseType, WebOverviewQuery, WebOverviewQueryResponse } from '~/queries/schema/schema-general'
import { QueryContext } from '~/queries/types'

import { dataNodeLogic } from '../DataNode/dataNodeLogic'

let uniqueNode = 0

export function WebOverview(props: {
    query: WebOverviewQuery
    cachedResults?: AnyResponseType
    context: QueryContext
    attachTo?: LogicWrapper | BuiltLogic
    uniqueKey?: string | number
}): JSX.Element | null {
    const { onData, loadPriority, dataNodeCollectionId } = props.context.insightProps ?? {}
    const [_key] = useState(() => `WebOverview.${uniqueNode++}`)
    const key = props.uniqueKey ? String(props.uniqueKey) : _key
    const logic = dataNodeLogic({
        query: props.query,
        key,
        cachedResults: props.cachedResults,
        loadPriority,
        onData,
        dataNodeCollectionId: dataNodeCollectionId ?? key,
    })
    const { response, responseLoading } = useValues(logic)
    useAttachedLogic(logic, props.attachTo)

    const webOverviewQueryResponse = response as WebOverviewQueryResponse | undefined

    const samplingRate = webOverviewQueryResponse?.samplingRate

    const numSkeletons = props.query.conversionGoal ? 4 : 5

    const canUseWebAnalyticsPreAggregatedTables = useFeatureFlag('SETTINGS_WEB_ANALYTICS_PRE_AGGREGATED_TABLES')
    const usedWebAnalyticsPreAggregatedTables =
        canUseWebAnalyticsPreAggregatedTables &&
        response &&
        'usedPreAggregatedTables' in response &&
        response.usedPreAggregatedTables

    // Convert WebOverviewItem to OverviewItem
    const overviewItems: OverviewItem[] =
        webOverviewQueryResponse?.results?.map((item) => ({
            key: item.key,
            value: item.value,
            previous: item.previous,
            changeFromPreviousPct: item.changeFromPreviousPct,
            kind: item.kind,
            isIncreaseBad: item.isIncreaseBad,
        })) || []

    return (
        <OverviewGrid
            items={overviewItems}
            loading={responseLoading}
            numSkeletons={numSkeletons}
            samplingRate={samplingRate}
            usedPreAggregatedTables={usedWebAnalyticsPreAggregatedTables}
            labelFromKey={labelFromKey}
            settingsLinkFromKey={settingsLinkFromKey}
            dashboardLinkFromKey={dashboardLinkFromKey}
            filterEmptyItems={filterEmptyRevenue}
            showBetaTags={(key) => key === 'revenue' || key === 'conversion revenue'}
        />
    )
}

const labelFromKey = (key: string): string => {
    switch (key) {
        case 'visitors':
            return 'Visitors'
        case 'views':
            return 'Page views'
        case 'sessions':
            return 'Sessions'
        case 'session duration':
            return 'Session duration'
        case 'bounce rate':
            return 'Bounce rate'
        case 'lcp score':
            return 'LCP Score'
        case 'conversion rate':
            return 'Conversion rate'
        case 'total conversions':
            return 'Total conversions'
        case 'unique conversions':
            return 'Unique conversions'
        case 'revenue':
            return 'Revenue'
        case 'conversion revenue':
            return 'Conversion revenue'
        default:
            return key
                .split(' ')
                .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
                .join(' ')
    }
}

const settingsLinkFromKey = (key: string): string | null => {
    switch (key) {
        case 'revenue':
        case 'conversion revenue':
            return urls.revenueSettings()
        default:
            return null
    }
}

const dashboardLinkFromKey = (key: string): string | null => {
    switch (key) {
        case 'revenue':
        case 'conversion revenue':
            return urls.revenueAnalytics()
        default:
            return null
    }
}

const filterEmptyRevenue = (item: OverviewItem): boolean => {
    return !(['revenue', 'conversion revenue'].includes(item.key) && item.value == null && item.previous == null)
}
