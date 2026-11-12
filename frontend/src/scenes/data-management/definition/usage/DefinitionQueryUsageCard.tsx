import { useChartTheme } from 'lib/charts/hooks'
import { AnalyticsMetricCard } from 'lib/components/AnalyticsMetricCard/AnalyticsMetricCard'
import { formatBucketLabel } from 'lib/utils/timeBuckets'

import type { PropertyUsageMetricsItemApi } from '~/generated/core/api.schemas'

export type DefinitionQueryUsage = Pick<
    PropertyUsageMetricsItemApi,
    'query_usage_30_day' | 'query_usage_previous_30_day' | 'query_usage_daily'
>

export interface DefinitionQueryUsageCardProps {
    usage: DefinitionQueryUsage | null
    loading: boolean
    failed: boolean
}

const formatCount = (value: number): string => value.toLocaleString()

function restingSubtitle(usage: DefinitionQueryUsage | null): string | undefined {
    if (!usage) {
        return undefined
    }
    if (usage.query_usage_30_day === 0) {
        return 'Not queried in the last 30 days'
    }
    if (usage.query_usage_previous_30_day == null) {
        return 'In the last 30 days'
    }
    return `vs. ${formatCount(usage.query_usage_previous_30_day)} prior`
}

export function DefinitionQueryUsageCard({ usage, loading, failed }: DefinitionQueryUsageCardProps): JSX.Element {
    const theme = useChartTheme()
    // A flat line at zero reads as a stray border, so an unused definition gets no sparkline.
    const daily = usage?.query_usage_30_day ? usage.query_usage_daily : []
    const previous = usage?.query_usage_previous_30_day ?? null
    const changePercent = usage && previous ? ((usage.query_usage_30_day - previous) / previous) * 100 : undefined
    const subtitle = restingSubtitle(usage)

    return (
        <AnalyticsMetricCard
            className="flex-1 basis-60"
            dataAttr="definition-usage-queries"
            title="Queries"
            value={usage?.query_usage_30_day}
            formatValue={formatCount}
            showChange={previous != null}
            change={changePercent != null ? { value: changePercent } : null}
            changeTooltip="Compared with the 30 days before"
            changeBesideSubtitle
            hoverChangeFromPreviousPoint
            goodDirection="up"
            data={daily.map((day) => day.count)}
            labels={daily.map((day) => day.date)}
            formatLabel={(label) => formatBucketLabel(label, 'day')}
            theme={theme}
            sparklineHeight={50}
            // The last day is today, so its count is still growing.
            sparklineDashedFromIndex={daily.length > 0 ? daily.length - 1 : undefined}
            restingSubtitle={subtitle ? <span translate="no">{subtitle}</span> : undefined}
            loading={loading}
            error={failed ? "Couldn't load the query count. Refresh the page to try again." : undefined}
        />
    )
}
