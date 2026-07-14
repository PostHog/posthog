import { BuiltLogic, LogicWrapper, useValues } from 'kea'
import { useState } from 'react'

import { reverseProxyCheckerLogic } from 'lib/components/ReverseProxyChecker/reverseProxyCheckerLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { useAttachedLogic } from 'lib/logic/scenes/useAttachedLogic'
import { capitalizeFirstLetter } from 'lib/utils/strings'

import { OverviewGrid } from '~/queries/nodes/OverviewGrid/OverviewGrid'
import { OverviewMetricCardGrid, OverviewMetricCardItem } from '~/queries/nodes/OverviewGrid/OverviewMetricCardGrid'
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
    const { featureFlags } = useValues(featureFlagLogic)
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

    const { hasReverseProxy } = useValues(reverseProxyCheckerLogic)

    const webOverviewQueryResponse = response as WebOverviewQueryResponse | undefined

    const samplingRate = webOverviewQueryResponse?.samplingRate

    const numSkeletons = props.query.conversionGoal ? 4 : 5

    const preComputeStrategy = webOverviewQueryResponse?.preComputeStrategy

    const showWarning = hasReverseProxy === false

    // Convert WebOverviewItem to OverviewItem
    // Handle both `results` (from direct query response) and `result` (from cached insight)
    const resultsArray = webOverviewQueryResponse?.results ?? (response as any)?.result
    const overviewItems: OverviewMetricCardItem[] =
        resultsArray?.map((item: any) => ({
            key: item.key,
            value: item.value,
            previous: item.previous,
            changeFromPreviousPct: item.changeFromPreviousPct,
            kind: item.kind,
            isIncreaseBad: item.isIncreaseBad,
            warning: showWarning
                ? `${capitalizeFirstLetter(item.key)} counts may be underreported. Set up a reverse proxy so that events are less likely to be intercepted by tracking blockers.`
                : undefined,
            warningLink: showWarning ? 'https://posthog.com/docs/advanced/proxy' : undefined,
        })) || []

    if (featureFlags[FEATURE_FLAGS.WEB_ANALYTICS_METRIC_CARDS]) {
        return (
            <OverviewMetricCardGrid
                items={overviewItems}
                loading={responseLoading}
                numSkeletons={numSkeletons}
                samplingRate={samplingRate}
                preComputeStrategy={preComputeStrategy}
                onDisablePrecompute={props.context.onDisableWebAnalyticsPrecompute}
                labelFromKey={labelFromKey}
            />
        )
    }

    return (
        <OverviewGrid
            items={overviewItems}
            loading={responseLoading}
            numSkeletons={numSkeletons}
            samplingRate={samplingRate}
            preComputeStrategy={preComputeStrategy}
            onDisablePrecompute={props.context.onDisableWebAnalyticsPrecompute}
            labelFromKey={labelFromKey}
        />
    )
}

export const labelFromKey = (key: string): string => {
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
        default:
            return key
                .split(' ')
                .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
                .join(' ')
    }
}
