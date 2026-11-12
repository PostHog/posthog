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

export function PropertyEventVolumeCard({ propertyName }: { propertyName: string }): JSX.Element {
    const { currentTeamId } = useValues(teamLogic)
    const theme = useChartTheme()
    const query = useMemo(() => propertyEventVolumeQuery(propertyName), [propertyName])
    const { response, responseLoading, responseError } = useValues(
        dataNodeLogic({ query, key: `definition-usage-event-volume-${currentTeamId}-${propertyName}` })
    )

    const results = (response as TrendsQueryResponse | null)?.results as TrendResult[] | undefined
    const current = results?.find((result) => result.compare_label === 'current')
    const previous = results?.find((result) => result.compare_label === 'previous')
    const changePercent =
        current && previous?.count ? ((current.count - previous.count) / previous.count) * 100 : undefined
    // A flat line at zero reads as a stray border, so a property with no events gets no sparkline.
    const sparkline = current?.count ? current : undefined
    const subtitle =
        current?.count === 0
            ? 'Not captured in the last 30 days'
            : previous
              ? `vs. ${formatCount(previous.count)} prior`
              : undefined

    return (
        <AnalyticsMetricCard
            className="flex-1 basis-60"
            dataAttr="definition-usage-event-volume"
            title="Events with this property"
            value={current?.count}
            formatValue={formatCount}
            showChange={previous != null}
            change={changePercent != null ? { value: changePercent } : null}
            changeTooltip="Compared with the 30 days before"
            changeBesideSubtitle
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
