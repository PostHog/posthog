import { useValues } from 'kea'

import { getColorVar } from 'lib/colors'
import { AppMetricsFilters } from 'lib/components/AppMetrics/AppMetricsFilters'
import { appMetricsLogic } from 'lib/components/AppMetrics/appMetricsLogic'
import { AppMetricsTrends } from 'lib/components/AppMetrics/AppMetricsTrends'
import { AppMetricSummary } from 'lib/components/AppMetrics/AppMetricSummary'

// app_source value the Node.js legacy-plugin producer writes into clickhouse_app_metrics2.
// Keep in sync with nodejs/src/cdp/legacy-plugins/app-metrics.ts.
const LEGACY_PLUGIN_APP_SOURCE = 'legacy_plugin'

const LEGACY_PLUGIN_METRIC_KEYS = ['succeeded', 'succeeded_on_retry', 'failed'] as const

const LEGACY_PLUGIN_METRICS_INFO: Record<string, { name: string; description: string; color: string }> = {
    succeeded: {
        name: 'Succeeded',
        description: 'Total number of events processed successfully',
        color: getColorVar('success'),
    },
    succeeded_on_retry: {
        name: 'Succeeded on retry',
        description: 'Events that failed initially but succeeded on a later retry',
        color: getColorVar('success'),
    },
    failed: {
        name: 'Failed',
        description: 'Total number of events that had errors during processing — see the Logs tab for details',
        color: getColorVar('danger'),
    },
}

export interface PipelineNodeMetricsProps {
    id: number | string
}

export function PipelineNodeMetrics({ id }: PipelineNodeMetricsProps): JSX.Element {
    const logicKey = `legacy-plugin-metrics-${id}`
    const logic = appMetricsLogic({
        logicKey,
        loadOnMount: true,
        loadOnChanges: true,
        forceParams: {
            appSource: LEGACY_PLUGIN_APP_SOURCE,
            appSourceId: String(id),
            metricName: [...LEGACY_PLUGIN_METRIC_KEYS],
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
                {LEGACY_PLUGIN_METRIC_KEYS.map((key) => (
                    <AppMetricSummary
                        key={key}
                        name={LEGACY_PLUGIN_METRICS_INFO[key].name}
                        description={LEGACY_PLUGIN_METRICS_INFO[key].description}
                        loading={appMetricsTrendsLoading}
                        timeSeries={getSingleTrendSeries(key)}
                        previousPeriodTimeSeries={getSingleTrendSeries(key, true)}
                        color={LEGACY_PLUGIN_METRICS_INFO[key].color}
                        colorIfZero={getColorVar('muted')}
                        hideIfZero={key === 'succeeded_on_retry'}
                    />
                ))}
            </div>
            <AppMetricsTrends appMetricsTrends={appMetricsTrends} loading={appMetricsTrendsLoading} />
        </div>
    )
}
