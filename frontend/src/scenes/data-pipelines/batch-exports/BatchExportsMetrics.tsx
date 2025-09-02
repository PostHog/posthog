import { useValues } from 'kea'

import { AppMetricSummary } from 'lib/components/AppMetrics/AppMetricSummary'
import { AppMetricsFilters } from 'lib/components/AppMetrics/AppMetricsFilters'
import { AppMetricsTrends } from 'lib/components/AppMetrics/AppMetricsTrends'
import { appMetricsLogic } from 'lib/components/AppMetrics/appMetricsLogic'

const METRICS_INFO = {
    succeeded: 'Total number of runs processed successfully',
    failed: 'Total number of runs that had errors during processing',
    canceled: 'Total number of runs that were canceled',
}

export function BatchExportsMetrics({ id }: { id: string }): JSX.Element {
    const logicKey = `batch-exports-metrics-${id}`
    const logic = appMetricsLogic({
        logicKey,
        loadOnChanges: true,
        forceParams: {
            appSource: 'batch_export',
            appSourceId: id,
            metricName: Object.keys(METRICS_INFO),
            breakdownBy: 'metric_name',
        },
    })

    const { appMetricsTrends, appMetricsTrendsLoading, getSingleTrendSeries } = useValues(logic)

    return (
        <div className="flex flex-col gap-2">
            <div className="flex flex-row gap-2 flex-wrap justify-end">
                <AppMetricsFilters logicKey={logicKey} />
            </div>

            <div className="flex flex-row gap-2 flex-wrap justify-center">
                <AppMetricSummary
                    name="Success"
                    description={METRICS_INFO.succeeded}
                    loading={appMetricsTrendsLoading}
                    timeSeries={getSingleTrendSeries('succeeded')}
                    previousPeriodTimeSeries={getSingleTrendSeries('succeeded', true)}
                />

                <AppMetricSummary
                    name="Failure"
                    description={METRICS_INFO.failed}
                    loading={appMetricsTrendsLoading}
                    timeSeries={getSingleTrendSeries('failed')}
                    previousPeriodTimeSeries={getSingleTrendSeries('failed', true)}
                />
                <AppMetricSummary
                    name="Canceled"
                    description={METRICS_INFO.canceled}
                    loading={appMetricsTrendsLoading}
                    timeSeries={getSingleTrendSeries('canceled')}
                    previousPeriodTimeSeries={getSingleTrendSeries('canceled', true)}
                />
            </div>
            <AppMetricsTrends appMetricsTrends={appMetricsTrends} loading={appMetricsTrendsLoading} />
        </div>
    )
}
