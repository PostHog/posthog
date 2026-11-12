import { useActions, useValues } from 'kea'
import type { ReactNode } from 'react'

import { materializationJobsLogic } from 'scenes/data-warehouse/saved_queries/materializationJobsLogic'
import { inheritedCadence, SyncFrequencyValue } from 'scenes/data-warehouse/saved_queries/SyncFrequencySelect'
import { urls } from 'scenes/urls'

import { SERVING_ENGINE } from '../suspension'
import { ModelHealthSummary, type ModelHealthSummaryProps } from './ModelHealthSummary'
import { modelScheduleLabel } from './modelScheduleLabel'
import { ModelTableSummary, type ModelTableSummaryProps } from './ModelTableSummary'
import { ModelViewSummary, type ModelViewSummaryProps } from './ModelViewSummary'
import { nodeDetailSceneLogic } from './nodeDetailSceneLogic'

export interface NodeDetailOverviewSummaries {
    TableSummary: (props: ModelTableSummaryProps) => JSX.Element
    ViewSummary: (props: ModelViewSummaryProps) => JSX.Element
    HealthSummary: (props: ModelHealthSummaryProps) => JSX.Element
}

const LEMON_SUMMARIES: NodeDetailOverviewSummaries = {
    TableSummary: ModelTableSummary,
    ViewSummary: ModelViewSummary,
    HealthSummary: ModelHealthSummary,
}

export function NodeDetailOverview({
    id,
    metadata,
    summaries = LEMON_SUMMARIES,
}: {
    id: string
    metadata?: ReactNode
    summaries?: NodeDetailOverviewSummaries
}): JSX.Element | null {
    const { TableSummary, ViewSummary, HealthSummary } = summaries
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
        nodeFrequency,
    } = useValues(materializationLogic)
    const { refreshMaterialization } = useActions(materializationLogic)
    const savedQuery = polledSavedQuery ?? sceneSavedQuery

    if (!node) {
        return null
    }
    if (node.type === 'table') {
        return (
            <TableSummary
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
            <ViewSummary
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
    // The saved setting is a lower bound: a downstream view can make this one run more often unless it is pinned.
    // The node in the scene store is not reloaded after a pin save, so the refreshed bounds win when they have loaded.
    const inherited =
        (nodeFrequency?.bounds.pinned ?? node.pinned)
            ? null
            : inheritedCadence(
                  savedQuery?.sync_frequency_bounds,
                  (savedQuery?.sync_frequency as SyncFrequencyValue | undefined) ?? null
              )
    const schedule = modelScheduleLabel({
        suspended,
        nodeType: node.type,
        savedQuery,
        savedQueryError,
        cadence: inherited?.cadence ?? savedQuery?.sync_frequency,
    })
    const latestJob = dataModelingJobs?.results?.[0]

    return (
        <HealthSummary
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
