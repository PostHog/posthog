import { useValues } from 'kea'

import { getColorVar } from 'lib/colors'
import { AppMetricSummary } from 'lib/components/AppMetrics/AppMetricSummary'
import { AppMetricsFilters } from 'lib/components/AppMetrics/AppMetricsFilters'
import { AppMetricsTrends } from 'lib/components/AppMetrics/AppMetricsTrends'
import { appMetricsLogic } from 'lib/components/AppMetrics/appMetricsLogic'

export const BATCH_EXPORT_METRICS_INFO: Record<string, { name: string; description: string; color: string }> = {
    succeeded: {
        name: 'Success',
        description: 'Total number of runs processed successfully',
        color: getColorVar('success'),
    },
    failed: {
        name: 'Failure',
        description: 'Total number of runs that had errors during processing',
        color: getColorVar('danger'),
    },
    canceled: {
        name: 'Canceled',
        description: 'Total number of runs that were canceled',
        color: getColorVar('warning'),
    },
}
export function BatchExportsMetrics({ id }: { id: string }): JSX.Element {
    const logicKey = `batch-exports-metrics-${id}`
    const logic = appMetricsLogic({
        logicKey,
        loadOnChanges: true,
        forceParams: {
            appSource: 'batch_export',
            appSourceId: id,
            metricName: Object.keys(BATCH_EXPORT_METRICS_INFO),
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
                {['succeeded', 'failed', 'canceled'].map((key) => (
                    <AppMetricSummary
                        key={key}
                        name={BATCH_EXPORT_METRICS_INFO[key].name}
                        description={BATCH_EXPORT_METRICS_INFO[key].description}
                        loading={appMetricsTrendsLoading}
                        timeSeries={getSingleTrendSeries(key)}
                        previousPeriodTimeSeries={getSingleTrendSeries(key, true)}
                        color={BATCH_EXPORT_METRICS_INFO[key].color}
                        colorIfZero={getColorVar('muted')}
                    />
                ))}
            </div>
            <AppMetricsTrends appMetricsTrends={appMetricsTrends} loading={appMetricsTrendsLoading} />
        </div>
    )
}
