import { useValues } from 'kea'

import { getColorVar } from 'lib/colors'
import { appMetricsLogic } from 'lib/components/AppMetrics/appMetricsLogic'
import { AppMetricSummary } from 'lib/components/AppMetrics/AppMetricSummary'

import { destinationTarget } from 'products/data_warehouse/frontend/shared/components/DestinationList'
import { ExternalDataDestinationApi } from 'products/warehouse_sources/frontend/generated/api.schemas'

import { DATA_WAREHOUSE_APP_SOURCE } from './DataWarehouseMetrics'

export interface DestinationMetricSummaryProps {
    sourceId: string
    destination: ExternalDataDestinationApi
}

/** What one destination has received from this source, across all of its tables. */
export function DestinationMetricSummary({ sourceId, destination }: DestinationMetricSummaryProps): JSX.Element {
    const logic = appMetricsLogic({
        logicKey: `dwh-destination-metrics-${sourceId}-${destination.id}`,
        loadOnMount: true,
        loadOnChanges: true,
        forceParams: {
            appSource: DATA_WAREHOUSE_APP_SOURCE,
            appSourceId: sourceId,
            // Runs record each destination on its own, without a schema, so this covers every
            // table on the source rather than needing one request per table.
            instanceId: destination.id,
            metricName: ['rows_synced'],
            breakdownBy: 'metric_name',
        },
    })

    const { appMetricsTrendsLoading, getSingleTrendSeries } = useValues(logic)
    const target = destinationTarget(destination)

    return (
        <AppMetricSummary
            name={destination.name}
            description={target ? `Rows written to ${target}` : `Rows written to ${destination.name}`}
            loading={appMetricsTrendsLoading}
            timeSeries={getSingleTrendSeries('rows_synced')}
            previousPeriodTimeSeries={getSingleTrendSeries('rows_synced', true)}
            color={getColorVar('success')}
            colorIfZero={getColorVar('muted')}
        />
    )
}
