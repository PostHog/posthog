import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { getColorVar } from 'lib/colors'
import { AppMetricsFilters } from 'lib/components/AppMetrics/AppMetricsFilters'
import { appMetricsLogic } from 'lib/components/AppMetrics/appMetricsLogic'
import { AppMetricsTrends } from 'lib/components/AppMetrics/AppMetricsTrends'
import { AppMetricSummary } from 'lib/components/AppMetrics/AppMetricSummary'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { teamLogic } from 'scenes/teamLogic'

import { destinationLookupLogic } from 'products/data_warehouse/frontend/shared/logics/destinationLookupLogic'
import { externalDataSourcesDestinationsRetrieve } from 'products/warehouse_sources/frontend/generated/api'

import { DestinationMetricSummary } from './DestinationMetricSummary'

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
        description: 'Rows read from the source. A run reads them once however many destinations it writes to.',
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
    const { featureFlags } = useValues(featureFlagLogic)
    const { currentTeamId } = useValues(teamLogic)
    const { destinations } = useValues(destinationLookupLogic)
    const { loadDestinations } = useActions(destinationLookupLogic)
    const [attachedIds, setAttachedIds] = useState<string[] | null>(null)

    const showDestinations = !!featureFlags[FEATURE_FLAGS.WAREHOUSE_MULTI_DESTINATION] && !schemaId

    useEffect(() => {
        if (!showDestinations) {
            return
        }
        loadDestinations()
        // Only the destinations this source actually writes to. The lookup holds every destination
        // the project has, and one the source does not use has nothing to chart.
        externalDataSourcesDestinationsRetrieve(String(currentTeamId), sourceId)
            .then((response) => setAttachedIds(response.destination_ids ?? []))
            .catch(() => setAttachedIds([]))
    }, [showDestinations, loadDestinations, currentTeamId, sourceId])

    const attached = destinations.filter((destination) => attachedIds?.includes(destination.id))
    // With a single destination every row already went there, so a breakdown would repeat the
    // totals above it.
    const destinationBreakdown = showDestinations && attached.length > 1 ? attached : []

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

            {destinationBreakdown.length > 0 && (
                <>
                    <h3 className="mb-0 mt-2">By destination</h3>
                    <div className="flex flex-row gap-2 flex-wrap justify-center">
                        {destinationBreakdown.map((destination) => (
                            <DestinationMetricSummary
                                key={destination.id}
                                sourceId={sourceId}
                                destination={destination}
                            />
                        ))}
                    </div>
                </>
            )}
        </div>
    )
}
