import { useValues } from 'kea'
import { useMemo } from 'react'

import { useChartTheme } from 'lib/charts/hooks'
import { AnalyticsMetricCard } from 'lib/components/AnalyticsMetricCard/AnalyticsMetricCard'
import { formatBucketLabel } from 'lib/utils/timeBuckets'
import { teamLogic } from 'scenes/teamLogic'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import type { TrendsQueryResponse } from '~/queries/schema/schema-general'
import type { TrendResult } from '~/types'

import { propertyEventVolumeQuery } from './propertyEventVolumeQuery'

const formatCount = (value: number): string => value.toLocaleString()

function compareResult(response: unknown, label: 'current' | 'previous'): TrendResult | undefined {
    const results = (response as TrendsQueryResponse | null)?.results as TrendResult[] | undefined
    return results?.find((result) => result.compare_label === label)
}

function changePercent(current: TrendResult | undefined, previous: TrendResult | undefined): number | undefined {
    if (!current || !previous?.count) {
        return undefined
    }
    return ((current.count - previous.count) / previous.count) * 100
}

function restingSubtitle(current: TrendResult | undefined, previous: TrendResult | undefined): string | undefined {
    if (current?.count === 0) {
        return 'Not captured in the last 30 days'
    }
    return previous ? `vs. ${formatCount(previous.count)} prior` : undefined
}

export function PropertyEventVolumeCard({ propertyName }: { propertyName: string }): JSX.Element {
    const { currentTeamId, timezone } = useValues(teamLogic)
    const theme = useChartTheme()
    const query = useMemo(() => propertyEventVolumeQuery(propertyName, timezone), [propertyName, timezone])
    const { response, responseLoading, responseError } = useValues(
        dataNodeLogic({ query, key: `definition-usage-event-volume-${currentTeamId}-${propertyName}` })
    )

    const current = compareResult(response, 'current')
    const previous = compareResult(response, 'previous')
    const change = changePercent(current, previous)
    // A flat line at zero reads as a stray border, so a property with no events gets no sparkline.
    const sparkline = current?.count ? current : undefined
    const subtitle = restingSubtitle(current, previous)

    return (
        <AnalyticsMetricCard
            className="flex-1 basis-60"
            dataAttr="definition-usage-event-volume"
            title="Events with this property"
            value={current?.count}
            formatValue={formatCount}
            showChange={previous != null}
            change={change != null ? { value: change } : null}
            changeTooltip="Compared with the 30 days before"
            changeBesideValue
            hoverChangeFromPreviousPoint
            goodDirection="up"
            data={sparkline?.data}
            labels={sparkline?.days}
            formatLabel={(label) => formatBucketLabel(label, 'day')}
            theme={theme}
            sparklineHeight={50}
            // The last day is today, so its count is still growing.
            sparklineDashedFromIndex={sparkline?.data.length ? sparkline.data.length - 1 : undefined}
            restingSubtitle={subtitle ? <span translate="no">{subtitle}</span> : undefined}
            emptyMessage="No events with this property in the last 30 days"
            loading={responseLoading || (!response && !responseError)}
            error={responseError ? "Couldn't load the event count. Refresh the page to try again." : undefined}
        />
    )
}
