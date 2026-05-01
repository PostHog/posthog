import { useValues } from 'kea'

import { getColorVar } from 'lib/colors'
import { AppMetricsFilters } from 'lib/components/AppMetrics/AppMetricsFilters'
import { appMetricsLogic } from 'lib/components/AppMetrics/appMetricsLogic'
import { AppMetricsTrends } from 'lib/components/AppMetrics/AppMetricsTrends'
import { AppMetricSummary } from 'lib/components/AppMetrics/AppMetricSummary'

export const DATA_WAREHOUSE_APP_SOURCE = 'warehouse_source_sync'

const DATA_WAREHOUSE_METRIC_KEYS = ['succeeded', 'failed', 'billing_limited', 'rows_synced'] as const

const DATA_WAREHOUSE_METRICS_INFO: Record<string, { name: string; description: string; color: string }> = {
    succeeded: {
        name: 'Successful syncs',
        description: 'Total number of sync jobs that completed successfully',
        color: getColorVar('success'),
    },
    failed: {
        name: 'Failed syncs',
        description: 'Total number of sync jobs that failed',
        color: getColorVar('danger'),
    },
    billing_limited: {
        name: 'Billing limited',
        description: 'Total number of sync jobs blocked due to billing limits',
        color: getColorVar('warning'),
    },
    rows_synced: {
        name: 'Rows synced',
        description: 'Total number of rows imported from the source',
        color: getColorVar('success'),
    },
}

export interface DataWarehouseMetricsProps {
    /** Identifies this metrics view — used as the logic key. */
    logicKey: string
    /** The source id (maps to app_metrics `app_source_id`). */
    sourceId: string
    /** Optional schema id — when set, scopes metrics to a single schema via `instance_id`. */
    schemaId?: string
}

export function DataWarehouseMetrics({ logicKey, sourceId, schemaId }: DataWarehouseMetricsProps): JSX.Element {
    const logic = appMetricsLogic({
        logicKey,
        loadOnMount: true,
        loadOnChanges: true,
        forceParams: {
            appSource: DATA_WAREHOUSE_APP_SOURCE,
            appSourceId: sourceId,
            instanceId: schemaId,
            metricName: [...DATA_WAREHOUSE_METRIC_KEYS],
            breakdownBy: 'metric_name',
        },
    })

    const { appMetricsTrends, appMetricsTrendsLoading, getSingleTrendSeries } = useValues(logic)

    const metricLabels = Object.fromEntries(
        DATA_WAREHOUSE_METRIC_KEYS.map((key) => [key, DATA_WAREHOUSE_METRICS_INFO[key].name])
    )

    return (
        <div className="flex flex-col gap-2">
            <div className="flex flex-row gap-2 flex-wrap justify-end">
                <AppMetricsFilters logicKey={logicKey} />
            </div>

            <div className="flex flex-row gap-2 flex-wrap justify-center">
                {DATA_WAREHOUSE_METRIC_KEYS.map((key) => (
                    <AppMetricSummary
                        key={key}
                        name={DATA_WAREHOUSE_METRICS_INFO[key].name}
                        description={DATA_WAREHOUSE_METRICS_INFO[key].description}
                        loading={appMetricsTrendsLoading}
                        timeSeries={getSingleTrendSeries(key)}
                        previousPeriodTimeSeries={getSingleTrendSeries(key, true)}
                        color={DATA_WAREHOUSE_METRICS_INFO[key].color}
                        colorIfZero={getColorVar('muted')}
                        hideIfZero={key === 'billing_limited'}
                    />
                ))}
            </div>
            <AppMetricsTrends
                appMetricsTrends={appMetricsTrends}
                loading={appMetricsTrendsLoading}
                metricLabels={metricLabels}
            />
        </div>
    )
}
