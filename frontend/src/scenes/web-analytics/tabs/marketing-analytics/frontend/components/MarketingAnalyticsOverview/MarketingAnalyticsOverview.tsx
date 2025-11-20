import { BuiltLogic, LogicWrapper, useValues } from 'kea'
import { useMemo, useState } from 'react'

import { useAttachedLogic } from 'lib/logic/scenes/useAttachedLogic'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { OverviewGrid, OverviewItem } from '~/queries/nodes/OverviewGrid/OverviewGrid'
import {
    AnyResponseType,
    MarketingAnalyticsAggregatedQuery,
    MarketingAnalyticsAggregatedQueryResponse,
} from '~/queries/schema/schema-general'
import { QueryContext } from '~/queries/types'

import { marketingAnalyticsSettingsLogic } from '../../logic/marketingAnalyticsSettingsLogic'
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
    const { response, responseLoading } = useValues(logic)
    const { conversion_goals } = useValues(marketingAnalyticsSettingsLogic)
    useAttachedLogic(logic, props.attachTo)

    const marketingOverviewQueryResponse = response as MarketingAnalyticsAggregatedQueryResponse | undefined

    const samplingRate = marketingOverviewQueryResponse?.samplingRate

    const validationWarnings = useMemo(() => validateConversionGoals(conversion_goals), [conversion_goals])

    // Convert results dict to array for rendering and map to OverviewItem
    const overviewItems: OverviewItem[] = marketingOverviewQueryResponse?.results
        ? Object.entries(marketingOverviewQueryResponse.results).map(([key, item]) => ({
              key,
              value: item.value,
              previous: item.previous,
              changeFromPreviousPct: item.changeFromPreviousPct,
              kind: item.kind,
              isIncreaseBad: item.isIncreaseBad,
          }))
        : []

    // Calculate number of skeletons based on expected metrics
    const conversionGoalMetrics = conversion_goals.length * 2 // Each conversion goal adds 2 metrics: goal + cost per conversion
    const numSkeletons = BASE_METRICS_COUNT + conversionGoalMetrics

    return (
        <>
            {validationWarnings && validationWarnings.length > 0 && (
                <MarketingAnalyticsValidationWarningBanner warnings={validationWarnings} />
            )}
            <OverviewGrid
                items={overviewItems}
                loading={responseLoading}
                numSkeletons={numSkeletons}
                samplingRate={samplingRate}
                usedPreAggregatedTables={false}
                labelFromKey={labelFromKey}
                settingsLinkFromKey={() => null}
                dashboardLinkFromKey={() => null}
                filterEmptyItems={filterEmptyMetrics}
                showBetaTags={() => false}
                compact={true}
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

const filterEmptyMetrics = (item: OverviewItem): boolean => {
    // Always show cost per metrics, even if they're null (they'll display as "-")
    if (item.key.toLowerCase().startsWith('cost per')) {
        return true
    }

    // Filter out other metrics that have no data and no comparison data
    const shouldShow = !(item.value == null && item.previous == null)

    return shouldShow
}
