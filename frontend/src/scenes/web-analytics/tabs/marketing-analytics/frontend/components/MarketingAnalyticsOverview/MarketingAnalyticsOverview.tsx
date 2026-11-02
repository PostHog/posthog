import { BuiltLogic, LogicWrapper, useActions, useValues } from 'kea'
import { useMemo, useState } from 'react'

import { useChartTheme } from 'lib/charts/hooks'
import { useAttachedLogic } from 'lib/logic/scenes/useAttachedLogic'
import { InsightErrorState } from 'scenes/insights/EmptyStates'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { OverviewMetricCardItem } from '~/queries/nodes/OverviewGrid/OverviewMetricCardGrid'
import {
    AnyResponseType,
    MarketingAnalyticsAggregatedQuery,
    MarketingAnalyticsAggregatedQueryResponse,
} from '~/queries/schema/schema-general'
import { QueryContext } from '~/queries/types'
import { MarketingAnalyticsNotReady } from '~/scenes/marketing-analytics/MarketingAnalyticsNotReady'

import { adPerformanceMetricKey } from 'products/marketing_analytics/frontend/adPerformanceMetrics'
import { adPerformanceTrendsLogic } from 'products/marketing_analytics/frontend/adPerformanceTrendsLogic'
import { AdPerformanceOverviewMetrics } from 'products/marketing_analytics/frontend/overview/AdPerformanceOverviewMetrics'

import { marketingAnalyticsLogic } from '../../logic/marketingAnalyticsLogic'
import { marketingAnalyticsSettingsLogic } from '../../logic/marketingAnalyticsSettingsLogic'
import {
    MARKETING_ANALYTICS_DATA_COLLECTION_NODE_ID,
    marketingAnalyticsTilesLogic,
} from '../../logic/marketingAnalyticsTilesLogic'
import {
    MarketingAnalyticsValidationWarningBanner,
    validateConversionGoals,
} from '../MarketingAnalyticsValidationWarningBanner'

const BASE_METRICS_COUNT = 6 // Total Cost, Total Clicks, CPC, CTR, Total Impressions, Reported Conversion

let uniqueNode = 0

export function MarketingAnalyticsOverview(props: {
    query: MarketingAnalyticsAggregatedQuery
    cachedResults?: AnyResponseType
    context: QueryContext
    attachTo?: LogicWrapper | BuiltLogic
    uniqueKey?: string | number
}): JSX.Element | null {
    const { onData, loadPriority, dataNodeCollectionId } = props.context.insightProps ?? {}
    const [_key] = useState(() => `MarketingAnalyticsOverview.${uniqueNode++}`)
    const key = props.uniqueKey ? String(props.uniqueKey) : _key
    const logic = dataNodeLogic({
        query: props.query,
        key,
        cachedResults: props.cachedResults,
        loadPriority,
        onData,
        dataNodeCollectionId: dataNodeCollectionId ?? key,
    })
    const { response, responseLoading, responseError, responseErrorObject, queryId } = useValues(logic)
    const { conversion_goals } = useValues(marketingAnalyticsSettingsLogic)
    useAttachedLogic(logic, props.attachTo)

    const marketingOverviewQueryResponse = response as MarketingAnalyticsAggregatedQueryResponse | undefined

    const { createAdPerformanceSparklineQuery } = useValues(marketingAnalyticsTilesLogic)
    const { tileColumnSelection } = useValues(marketingAnalyticsLogic)
    const { setTileColumnSelection } = useActions(marketingAnalyticsLogic)
    const { sparklines } = useValues(
        adPerformanceTrendsLogic({
            query: createAdPerformanceSparklineQuery(props.query),
            queryKey: `${key}-sparklines`,
            dataNodeCollectionId: dataNodeCollectionId ?? MARKETING_ANALYTICS_DATA_COLLECTION_NODE_ID,
        })
    )
    const sparklineTheme = useChartTheme()
    const samplingRate = marketingOverviewQueryResponse?.samplingRate

    const validationWarnings = useMemo(() => validateConversionGoals(conversion_goals), [conversion_goals])

    const overviewItems: OverviewMetricCardItem[] = marketingOverviewQueryResponse?.results
        ? Object.entries(marketingOverviewQueryResponse.results).map(([key, item]) => {
              const metric = adPerformanceMetricKey(key)
              return {
                  key,
                  value: item.value,
                  previous: item.previous,
                  changeFromPreviousPct: item.changeFromPreviousPct,
                  kind: item.kind,
                  isIncreaseBad: item.isIncreaseBad,
                  selected: metric ? tileColumnSelection === metric : undefined,
                  onClick: metric ? () => setTileColumnSelection(metric) : undefined,
                  sparkline: metric && typeof item.value === 'number' ? sparklines[metric] : undefined,
              }
          })
        : []

    // Calculate number of skeletons based on expected metrics
    const conversionGoalMetrics = conversion_goals.length * 2 // Each conversion goal adds 2 metrics: goal + cost per conversion
    const numSkeletons = BASE_METRICS_COUNT + conversionGoalMetrics

    const hasResults = overviewItems.length > 0
    if (responseError && !responseLoading && !hasResults) {
        return <InsightErrorState title={responseError} queryId={responseErrorObject?.queryId ?? queryId} />
    }

    // A cold precompute window comes back as an empty result, which the metric grid would render as a row
    // of blanks. Say it is still being prepared instead.
    if (!responseLoading && marketingOverviewQueryResponse?.precomputeNotReady) {
        return <MarketingAnalyticsNotReady />
    }

    // Combine validation warnings with any backend warnings (e.g. skipped conversion goals)
    const allWarnings = [
        ...(validationWarnings ?? []),
        ...(responseError && hasResults ? [{ message: responseError, link: undefined } as const] : []),
    ]

    return (
        <>
            {allWarnings.length > 0 && <MarketingAnalyticsValidationWarningBanner warnings={allWarnings} />}
            <AdPerformanceOverviewMetrics
                viewKey={dataNodeCollectionId ?? MARKETING_ANALYTICS_DATA_COLLECTION_NODE_ID}
                items={overviewItems.filter(filterEmptyMetrics)}
                loading={responseLoading}
                numSkeletons={numSkeletons}
                samplingRate={samplingRate}
                sparklineTheme={sparklineTheme}
                labelFromKey={(key) => <span className="[overflow-wrap:anywhere]">{labelFromKey(key)}</span>}
            />
        </>
    )
}

const labelFromKey = (key: string): string => {
    // Cost Per already formatted nicely
    if (key.startsWith('Cost Per ')) {
        return key
    }

    // Default: capitalize each word
    return key
        .split(' ')
        .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
        .join(' ')
}

const filterEmptyMetrics = (item: OverviewMetricCardItem): boolean => {
    // Always show cost per metrics, even if they're null (they'll display as "-")
    if (item.key.toLowerCase().startsWith('cost per')) {
        return true
    }

    // Filter out other metrics that have no data and no comparison data
    const shouldShow = !(item.value == null && item.previous == null)

    return shouldShow
}
