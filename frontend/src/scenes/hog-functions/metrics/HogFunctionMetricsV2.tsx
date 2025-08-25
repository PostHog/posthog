import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { AppMetricSummary } from 'lib/components/AppMetrics/AppMetricSummary'
import { AppMetricsFilters } from 'lib/components/AppMetrics/AppMetricsFilters'
import { appMetricsLogic } from 'lib/components/AppMetrics/appMetricsLogic'

import { HogFunctionMetricsLogicProps } from './hogFunctionMetricsLogic'

const METRICS_INFO = {
    succeeded: 'Total number of events processed successfully',
    failed: 'Total number of events that had errors during processing',
    filtered: 'Total number of events that were filtered out',
    dropped: 'Total number of events that were dropped during processing',
    disabled_temporarily:
        'Total number of events that were skipped due to the destination being temporarily disabled (due to issues such as the destination being down or rate-limited)',
    disabled_permanently:
        'Total number of events that were skipped due to the destination being permanently disabled (due to prolonged issues with the destination)',
}

export function HogFunctionMetricsV2({ id }: HogFunctionMetricsLogicProps): JSX.Element {
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

    const { appMetricsTrendsLoading, getSingleTrendSeries } = useValues(logic)
    const { loadAppMetricsTrends, loadAppMetricsTrendsPreviousPeriod } = useActions(logic)

    useEffect(() => {
        loadAppMetricsTrends()
        loadAppMetricsTrendsPreviousPeriod()
    }, [loadAppMetricsTrends, loadAppMetricsTrendsPreviousPeriod])

    return (
        <div>
            <AppMetricsFilters logicKey={`hog-function-metrics-${id}`} />

            <div className="flex flex-row gap-2 mb-2 flex-wrap justify-center">
                <AppMetricSummary
                    name="Success"
                    color="data-color-1"
                    description={METRICS_INFO.succeeded}
                    loading={appMetricsTrendsLoading}
                    timeSeries={getSingleTrendSeries('succeeded')}
                    previousPeriodTimeSeries={getSingleTrendSeries('succeeded', true)}
                />

                <AppMetricSummary
                    name="Failure"
                    color="data-color-1"
                    description={METRICS_INFO.failed}
                    loading={appMetricsTrendsLoading}
                    timeSeries={getSingleTrendSeries('failed')}
                    previousPeriodTimeSeries={getSingleTrendSeries('failed', true)}
                />

                <AppMetricSummary
                    name="Filtered"
                    color="data-color-1"
                    description={METRICS_INFO.filtered}
                    loading={appMetricsTrendsLoading}
                    timeSeries={getSingleTrendSeries('filtered')}
                    previousPeriodTimeSeries={getSingleTrendSeries('filtered', true)}
                />

                <AppMetricSummary
                    name="Disabled"
                    color="data-color-1"
                    description={METRICS_INFO.disabled_permanently}
                    loading={appMetricsTrendsLoading}
                    timeSeries={getSingleTrendSeries('disabled_permanently')}
                    previousPeriodTimeSeries={getSingleTrendSeries('disabled_permanently', true)}
                />
            </div>
        </div>
    )
}
