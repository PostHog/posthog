import { useActions, useValues } from 'kea'

import { TZLabel } from 'lib/components/TZLabel'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { materializationJobsLogic } from 'scenes/data-warehouse/saved_queries/materializationJobsLogic'
import { CADENCE_LABELS, modeDisabledReason } from 'scenes/data-warehouse/saved_queries/SyncFrequencySelect'
import { urls } from 'scenes/urls'

import { DataModelingSyncInterval } from '~/types'

import { ModelHealthSummary } from 'products/data_modeling/frontend/nodeDetail/ModelHealthSummary'
import { SERVING_ENGINE } from 'products/data_modeling/frontend/suspension'

import { nodeDetailSceneLogic } from './nodeDetailSceneLogic'

export function NodeDetailOverview({ id }: { id: string }): JSX.Element | null {
    const {
        node,
        savedQuery: sceneSavedQuery,
        isMaterialized,
        savedQueryError,
        effectiveLastRunAt,
        effectiveLastRunStatus,
    } = useValues(nodeDetailSceneLogic({ id }))
    const materializationLogic = materializationJobsLogic({
        viewId: node?.saved_query_id ?? '',
        kind: node?.type === 'endpoint' ? 'endpoint' : 'view',
    })
    const {
        savedQuery: polledSavedQuery,
        dataModelingJobs,
        dataModelingJobsLoading,
        dataModelingJobsError,
        savedQueryError: statusRefreshError,
        savedQueryLoading: statusRefreshing,
        lastSuccessfulSyncAt,
    } = useValues(materializationLogic)
    const { refreshMaterialization } = useActions(materializationLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const savedQuery = polledSavedQuery ?? sceneSavedQuery

    if (!node) {
        return null
    }
    if (!(savedQuery?.is_materialized ?? isMaterialized)) {
        return node.type === 'table' ? (
            effectiveLastRunAt ? (
                <p className="text-sm text-secondary mb-0">
                    Last synced <TZLabel time={effectiveLastRunAt} />
                </p>
            ) : null
        ) : (
            <p className="text-sm text-secondary mb-0">
                This view runs its query when used. Materialize it to store results and refresh them on a schedule.
            </p>
        )
    }
    // Only ClickHouse serves queries, so a marker on a shadow engine means the comparison
    // run stopped, not that this model stopped refreshing.
    const suspension = savedQuery?.suspended?.[SERVING_ENGINE]
    const suspended = !!featureFlags[FEATURE_FLAGS.DATA_MODELING_SUSPEND_FAILING_NODES] && !!suspension
    const cadence = savedQuery?.sync_frequency
    const schedule = suspended
        ? 'Suspended after repeated failures'
        : node.type === 'endpoint'
          ? 'Managed by endpoint'
          : modeDisabledReason(savedQuery?.sync_frequency_bounds)
            ? 'Managed by PostHog'
            : !savedQuery
              ? savedQueryError
                  ? 'Schedule unavailable'
                  : null
              : !cadence || cadence === 'never'
                ? 'Paused'
                : `Every ${CADENCE_LABELS[cadence as DataModelingSyncInterval] ?? cadence}`
    const latestJob = dataModelingJobs?.results?.[0]

    return (
        <ModelHealthSummary
            status={latestJob?.status ?? savedQuery?.status ?? effectiveLastRunStatus}
            suspended={suspended}
            error={suspension?.reason ?? latestJob?.error ?? savedQuery?.latest_error ?? node.last_run_error}
            lastSuccessfulSyncAt={lastSuccessfulSyncAt}
            historyLoaded={dataModelingJobs !== null}
            historyError={dataModelingJobsError || statusRefreshError}
            onRetry={refreshMaterialization}
            retryLoading={dataModelingJobsLoading || statusRefreshing}
            schedule={schedule}
            lineageUrl={urls.nodeDetail(id, 'lineage')}
            downstreamCount={node.downstream_count}
        />
    )
}
