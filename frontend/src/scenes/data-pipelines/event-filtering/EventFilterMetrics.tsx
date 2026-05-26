import { useValues } from 'kea'

import { getColorVar } from 'lib/colors'
import { AppMetricsFilters } from 'lib/components/AppMetrics/AppMetricsFilters'
import { appMetricsLogic } from 'lib/components/AppMetrics/appMetricsLogic'
import { AppMetricsTrends } from 'lib/components/AppMetrics/AppMetricsTrends'
import { AppMetricSummary } from 'lib/components/AppMetrics/AppMetricSummary'

const EVENT_FILTER_METRIC_KEYS = ['dropped', 'would_be_dropped'] as const

const EVENT_FILTER_METRICS_INFO: Record<string, { name: string; description: string; color: string }> = {
    dropped: {
        name: 'Dropped',
        description: 'Approximate number of events dropped by the filter in live mode',
        color: getColorVar('danger'),
    },
    would_be_dropped: {
        name: 'Would be dropped',
        description: 'Approximate number of events that matched the filter in dry run mode (not actually dropped)',
        color: getColorVar('warning'),
    },
}

export function EventFilterMetrics({ filterId }: { filterId: string | null }): JSX.Element | null {
    const logicKey = `event-filter-metrics-${filterId ?? 'none'}`

    const logic = filterId
        ? appMetricsLogic({
              logicKey,
              loadOnMount: true,
              loadOnChanges: true,
              forceParams: {
                  appSource: 'event_filter',
                  appSourceId: filterId,
                  metricName: [...EVENT_FILTER_METRIC_KEYS],
                  breakdownBy: 'metric_name',
              },
          })
        : null

    const { appMetricsTrends, appMetricsTrendsLoading, getSingleTrendSeries } = useValues(
        logic ?? appMetricsLogic({ logicKey: 'noop' })
    )

    if (!filterId) {
        return null
    }

    return (
        <div className="flex flex-col gap-2">
            <div className="flex flex-row gap-2 flex-wrap justify-end">
                <AppMetricsFilters logicKey={logicKey} />
            </div>
            <div className="flex flex-row gap-2 flex-wrap justify-center">
                {EVENT_FILTER_METRIC_KEYS.map((key) => (
                    <AppMetricSummary
                        key={key}
                        name={EVENT_FILTER_METRICS_INFO[key].name}
                        description={EVENT_FILTER_METRICS_INFO[key].description}
                        loading={appMetricsTrendsLoading}
                        timeSeries={getSingleTrendSeries(key)}
                        previousPeriodTimeSeries={getSingleTrendSeries(key, true)}
                        color={EVENT_FILTER_METRICS_INFO[key].color}
                        colorIfZero={getColorVar('muted')}
                    />
                ))}
            </div>
            <AppMetricsTrends appMetricsTrends={appMetricsTrends} loading={appMetricsTrendsLoading} />
            <p className="text-muted text-xs">
                These counts are approximate. The actual number of dropped events may differ by a small percentage.
            </p>
        </div>
    )
}
