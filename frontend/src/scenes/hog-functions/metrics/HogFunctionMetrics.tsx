import { useValues } from 'kea'

import { AppMetricSummary } from 'lib/components/AppMetrics/AppMetricSummary'
import { AppMetricsFilters } from 'lib/components/AppMetrics/AppMetricsFilters'
import { AppMetricsTrends } from 'lib/components/AppMetrics/AppMetricsTrends'
import { appMetricsLogic } from 'lib/components/AppMetrics/appMetricsLogic'

import { HogFunctionMetricsLogicProps } from './hogFunctionMetricsLogic'

const METRICS_INFO = {
    succeeded: 'Total number of events processed successfully',
    failed: 'Total number of events that had errors during processing',
    filtered: 'Total number of events that were filtered out',
    dropped: 'Total number of events that were dropped during processing',
    disabled_permanently:
        'Total number of events that were skipped due to the destination being permanently disabled (due to prolonged issues with the destination)',
}

export function HogFunctionMetrics({ id }: HogFunctionMetricsLogicProps): JSX.Element {
    const logic = appMetricsLogic({
        logicKey: `hog-function-metrics-${id}`,
        loadOnChanges: true,
        forceParams: {
            appSource: 'hog_function',
            appSourceId: id,
            metricName: ['succeeded', 'failed', 'filtered', 'disabled_permanently'],
            breakdownBy: 'metric_name',
        },
    })

    const { appMetricsTrends, appMetricsTrendsLoading, getSingleTrendSeries } = useValues(logic)

    return (
        <div className="flex flex-col gap-2">
            <div className="flex flex-row gap-2 flex-wrap justify-end">
                <AppMetricsFilters logicKey={`hog-function-metrics-${id}`} />
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
                    name="Filtered"
                    description={METRICS_INFO.filtered}
                    loading={appMetricsTrendsLoading}
                    timeSeries={getSingleTrendSeries('filtered')}
                    previousPeriodTimeSeries={getSingleTrendSeries('filtered', true)}
                />

                <AppMetricSummary
                    name="Disabled"
                    description={METRICS_INFO.disabled_permanently}
                    loading={appMetricsTrendsLoading}
                    timeSeries={getSingleTrendSeries('disabled_permanently')}
                    previousPeriodTimeSeries={getSingleTrendSeries('disabled_permanently', true)}
                />
            </div>
            <AppMetricsTrends appMetricsTrends={appMetricsTrends} loading={appMetricsTrendsLoading} />
        </div>
    )
}
