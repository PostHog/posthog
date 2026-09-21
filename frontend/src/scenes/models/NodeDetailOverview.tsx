import { useActions, useValues } from 'kea'
import type { ReactNode } from 'react'

import { materializationJobsLogic } from 'scenes/data-warehouse/saved_queries/materializationJobsLogic'
import { CADENCE_LABELS, modeDisabledReason } from 'scenes/data-warehouse/saved_queries/SyncFrequencySelect'
import { urls } from 'scenes/urls'

import { DataModelingSyncInterval } from '~/types'

import { ModelHealthSummary } from 'products/data_modeling/frontend/nodeDetail/ModelHealthSummary'
import { ModelTableSummary } from 'products/data_modeling/frontend/nodeDetail/ModelTableSummary'
import { ModelViewSummary } from 'products/data_modeling/frontend/nodeDetail/ModelViewSummary'
import { SERVING_ENGINE } from 'products/data_modeling/frontend/suspension'

import { nodeDetailSceneLogic } from './nodeDetailSceneLogic'

export function NodeDetailOverview({ id, metadata }: { id: string; metadata?: ReactNode }): JSX.Element | null {
    const sceneLogic = nodeDetailSceneLogic({ id })
    const {
        node,
        savedQuery: sceneSavedQuery,
        isMaterialized,
        savedQueryError,
        effectiveLastRunStatus,
        tableDetails,
        tableDetailsAccessDenied,
        tableDetailsLoading,
        tableDetailsError,
    } = useValues(sceneLogic)
    const { loadTableDetails } = useActions(sceneLogic)
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
    const savedQuery = polledSavedQuery ?? sceneSavedQuery

    if (!node) {
        return null
    }
    if (node.type === 'table') {
        return (
            <ModelTableSummary
                id={id}
                node={node}
                table={tableDetails?.table ?? null}
                source={tableDetails?.source ?? null}
                schema={tableDetails?.schema ?? null}
                loading={tableDetailsLoading}
                error={tableDetailsError}
                accessDenied={tableDetailsAccessDenied}
                onRetry={loadTableDetails}
                metadata={metadata}
            />
        )
    }
    if (!(savedQuery?.is_materialized ?? isMaterialized)) {
        return (
            <ModelViewSummary
                downstreamCount={node.downstream_count}
                lineageUrl={urls.nodeDetail(id, 'lineage')}
                metadata={metadata}
            />
        )
    }
    // Only ClickHouse serves queries, so a marker on a shadow engine means the comparison
    // run stopped, not that this model stopped refreshing.
    const suspension = (savedQuery?.suspended ?? node.suspended)?.[SERVING_ENGINE]
    const suspended = !!suspension
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
            metadata={metadata}
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
