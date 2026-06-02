import { BuiltLogic, LogicWrapper, useValues } from 'kea'
import { useState } from 'react'

import { IconWarning } from '@posthog/icons'
import { Link } from '@posthog/lemon-ui'

import { PreAggregatedBadge } from 'lib/components/PreAggregatedBadge'
import { reverseProxyCheckerLogic } from 'lib/components/ReverseProxyChecker/reverseProxyCheckerLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { Metric } from 'lib/hog-charts'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { useAttachedLogic } from 'lib/logic/scenes/useAttachedLogic'
import { capitalizeFirstLetter, isNotNil } from 'lib/utils'
import { teamLogic } from 'scenes/teamLogic'

import {
    formatItem,
    getOverviewItemTooltip,
    OverviewGrid,
    OverviewItem,
    OverviewItemRenderHelpers,
} from '~/queries/nodes/OverviewGrid/OverviewGrid'
import { AnyResponseType, WebOverviewQuery, WebOverviewQueryResponse } from '~/queries/schema/schema-general'
import { QueryContext } from '~/queries/types'

import { dataNodeLogic } from '../DataNode/dataNodeLogic'

// Sentinel value the backend emits for changeFromPreviousPct when the previous period was 0
const CHANGE_UNAVAILABLE = 999999

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

    const usedWebAnalyticsPreAggregatedTables =
        response && 'usedPreAggregatedTables' in response && response.usedPreAggregatedTables
    const usedWebAnalyticsLazyPrecompute = response && 'usedLazyPrecompute' in response && response.usedLazyPrecompute

    const showWarning = hasReverseProxy === false && !!featureFlags[FEATURE_FLAGS.WEB_ANALYTICS_EMPTY_ONBOARDING]

    // Convert WebOverviewItem to OverviewItem
    // Handle both `results` (from direct query response) and `result` (from cached insight)
    const resultsArray = webOverviewQueryResponse?.results ?? (response as any)?.result
    const overviewItems: OverviewItem[] =
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

    return (
        <OverviewGrid
            items={overviewItems}
            loading={responseLoading}
            numSkeletons={numSkeletons}
            samplingRate={samplingRate}
            usedPreAggregatedTables={usedWebAnalyticsPreAggregatedTables}
            usedLazyPrecompute={usedWebAnalyticsLazyPrecompute}
            labelFromKey={labelFromKey}
            renderItem={(item, helpers) => <WebOverviewMetric item={item} helpers={helpers} />}
        />
    )
}

function WebOverviewMetric({ item, helpers }: { item: OverviewItem; helpers: OverviewItemRenderHelpers }): JSX.Element {
    const { baseCurrency } = useValues(teamLogic)
    const { label, usedPreAggregatedTables, usedLazyPrecompute } = helpers

    const numericValue = typeof item.value === 'number' ? item.value : undefined

    // The change pill is hidden when there's nothing to compare against or the backend signals it's unavailable
    const hasChange = isNotNil(item.changeFromPreviousPct) && Math.abs(item.changeFromPreviousPct) < CHANGE_UNAVAILABLE
    const change = hasChange ? { value: item.changeFromPreviousPct as number } : null

    const title = (
        <span className="inline-flex items-center gap-1">
            {label}
            {item.warning && (
                <Tooltip
                    interactive={!!item.warningLink}
                    title={
                        <div>
                            {item.warning}
                            {item.warningLink && (
                                <>
                                    {' '}
                                    <Link to={item.warningLink} className="text-link">
                                        Learn more
                                    </Link>
                                </>
                            )}
                        </div>
                    }
                >
                    <IconWarning className="text-warning h-3.5 w-3.5 cursor-pointer" />
                </Tooltip>
            )}
        </span>
    )

    return (
        <div className="relative flex-1 min-w-[10rem] border bg-surface-primary rounded p-3">
            {/* Rendered as a sibling of the Tooltip trigger so hovering the badge
                does not also surface the cell's metric tooltip. */}
            {usedLazyPrecompute ? (
                <PreAggregatedBadge variant="precomputed" />
            ) : usedPreAggregatedTables ? (
                <PreAggregatedBadge variant="preagg" />
            ) : null}
            <Tooltip title={getOverviewItemTooltip(item, label, baseCurrency)}>
                <div className="w-full">
                    <Metric
                        title={title}
                        value={numericValue ?? 0}
                        change={change}
                        goodDirection={item.isIncreaseBad ? 'down' : 'up'}
                        formatValue={(v) =>
                            numericValue == null ? '-' : formatItem(v, item.kind, { currency: baseCurrency })
                        }
                        subtitle={
                            isNotNil(item.previous)
                                ? `vs. ${formatItem(item.previous, item.kind, { currency: baseCurrency })} previous`
                                : undefined
                        }
                    />
                </div>
            </Tooltip>
        </div>
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
        default:
            return key
                .split(' ')
                .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
                .join(' ')
    }
}
