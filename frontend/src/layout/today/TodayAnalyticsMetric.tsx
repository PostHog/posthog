import { useValues } from 'kea'

import { IconGraph } from '@posthog/icons'
import {
    Metric,
    MetricDelta,
    MetricHeader,
    MetricSparkline,
    MetricTitle,
    MetricValue,
} from '@posthog/quill-components/metric'

import { useChartTheme } from 'lib/charts/hooks'
import { METRIC_SHOW_CHANGE_DEFAULT } from 'lib/components/Metric/metricSummary'
import { formatAggregationAxisValue } from 'lib/insights/aggregationAxisFormat'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { InsightShortId } from '~/types'

import type { SidebarMetricApi } from 'products/ui_customization/frontend/generated/api.schemas'

import { todayAnalyticsMetricLogic } from './todayAnalyticsMetricLogic'
import { TodayPaneOption } from './TodayPaneOption'
import { TodayPaneRow } from './TodayPaneRow'

interface TodayAnalyticsMetricProps {
    item: SidebarMetricApi
    value: string
    active: boolean
}

/** A number from a trends insight, with its sparkline. Opens the insight. */
export function TodayAnalyticsMetric({ item, value, active }: TodayAnalyticsMetricProps): JSX.Element {
    const { insight, insightLoading, loadFailed, metric } = useValues(
        todayAnalyticsMetricLogic({ shortId: item.insight })
    )
    const theme = useChartTheme()
    const { baseCurrency } = useValues(teamLogic)
    const to = urls.insightView(item.insight as InsightShortId)

    if (!metric) {
        // A missing insight and one without a number still open the insight, whose page says why.
        const meta = loadFailed ? 'Couldn’t load' : insightLoading ? undefined : !insight ? 'Not found' : undefined
        return (
            <TodayPaneRow
                value={value}
                label={item.label}
                meta={meta}
                icon={<IconGraph />}
                to={to}
                active={active}
                dataAttr="analytics-sidebar-metric"
            />
        )
    }
    return (
        <TodayPaneOption
            value={value}
            to={to}
            active={active}
            title={item.label}
            className="h-auto py-1.5"
            data-attr="analytics-sidebar-metric"
        >
            <Metric
                value={metric.value}
                change={metric.change}
                showChange={metric.trendsFilter?.metricShowChange ?? METRIC_SHOW_CHANGE_DEFAULT}
                data={metric.data}
                labels={metric.labels}
                theme={theme}
                formatValue={(number) => formatAggregationAxisValue(metric.trendsFilter, number, baseCurrency)}
                sparklineHeight={24}
                className="w-full px-0"
            >
                <MetricHeader>
                    <MetricTitle className="truncate text-xs font-normal text-muted-foreground">
                        {item.label}
                    </MetricTitle>
                    <MetricDelta />
                </MetricHeader>
                <MetricValue className="text-xl" />
                <MetricSparkline className="mt-1" />
            </Metric>
        </TodayPaneOption>
    )
}
