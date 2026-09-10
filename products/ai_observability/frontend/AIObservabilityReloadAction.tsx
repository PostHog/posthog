import { useActions, useValues } from 'kea'
import React from 'react'

import { IconRefresh } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { dayjs } from 'lib/dayjs'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { useAttachedLogic } from 'lib/logic/scenes/useAttachedLogic'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'

import { dataNodeCollectionLogic } from '~/queries/nodes/DataNode/dataNodeCollectionLogic'
import { DashboardPlacement } from '~/types'

import { AI_OBSERVABILITY_DATA_COLLECTION_NODE_ID, aiObservabilitySharedLogic } from './aiObservabilitySharedLogic'
import { EVALUATION_METRICS_COLLECTION_ID } from './evaluations/components/EvaluationMetrics'
import { evaluationMetricsLogic } from './evaluations/evaluationMetricsLogic'
import { llmEvaluationsLogic } from './evaluations/llmEvaluationsLogic'
import { aiObservabilityDashboardLogic } from './tabs/aiObservabilityDashboardLogic'
import { aiObservabilitySessionsViewLogic } from './tabs/aiObservabilitySessionsViewLogic'

export function AIObservabilityReloadAction(): JSX.Element {
    const { activeTab } = useValues(aiObservabilitySharedLogic)
    const { selectedDashboardId } = useValues(aiObservabilityDashboardLogic)

    const shouldUseDashboardLogic = !!(selectedDashboardId && activeTab === 'dashboard')

    // Memoize per-id so the previous dashboardLogic.<id> store path is released cleanly
    // before the next one mounts; an unmemoized call on every render leaves selectors/
    // listeners reading from an unmounted store and Kea throws "Can not find path".
    const dashboardLogicInstance = React.useMemo(
        () =>
            selectedDashboardId
                ? dashboardLogic({ id: selectedDashboardId, placement: DashboardPlacement.Builtin })
                : null,
        [selectedDashboardId]
    )
    const fallbackLogicInstance = React.useMemo(
        () => dashboardLogic({ id: 0, placement: DashboardPlacement.Builtin }),
        []
    )
    const boundLogic = dashboardLogicInstance || fallbackLogicInstance
    useAttachedLogic(boundLogic, aiObservabilitySharedLogic)

    const {
        itemsLoading: dashboardLoading,
        effectiveLastRefresh,
        refreshMetrics,
        dashboardLoadData,
    } = useValues(boundLogic)
    const { triggerDashboardRefresh } = useActions(boundLogic)

    const { reloadAll } = useActions(dataNodeCollectionLogic({ key: AI_OBSERVABILITY_DATA_COLLECTION_NODE_ID }))
    const { reloadAll: reloadEvaluationMetrics } = useActions(
        dataNodeCollectionLogic({ key: EVALUATION_METRICS_COLLECTION_ID })
    )
    const { refreshMetrics: refreshEvaluationMetrics } = useActions(evaluationMetricsLogic)
    const { loadEvaluations } = useActions(llmEvaluationsLogic)
    const { sessionsLoading } = useValues(aiObservabilitySessionsViewLogic)
    const { loadSessions } = useActions(aiObservabilitySessionsViewLogic)

    const isLoading = shouldUseDashboardLogic ? dashboardLoading : activeTab === 'sessions' ? sessionsLoading : false
    const lastRefresh = shouldUseDashboardLogic ? effectiveLastRefresh : null

    const handleRefresh = (): void => {
        if (activeTab === 'dashboard') {
            triggerDashboardRefresh()
        } else if (activeTab === 'evaluations') {
            // Refresh evaluations list and metrics
            loadEvaluations()
            refreshEvaluationMetrics()
            reloadEvaluationMetrics()
        } else if (activeTab === 'sessions') {
            // The sessions list is a custom loader, not part of the data-node collection reloadAll() drives.
            // Force a recompute so the button surfaces newly-ingested sessions instead of a cached result.
            loadSessions({ refresh: 'force_blocking' })
        } else {
            reloadAll()
        }
    }

    return (
        <LemonButton
            onClick={handleRefresh}
            type="secondary"
            icon={isLoading ? <Spinner textColored /> : <IconRefresh />}
            size="small"
            disabledReason={isLoading ? 'Loading...' : undefined}
        >
            <span className="dashboard-items-action-refresh-text">
                {isLoading ? (
                    <>
                        {shouldUseDashboardLogic && refreshMetrics?.total ? (
                            <>
                                {dashboardLoadData?.action === 'initial_load' ? 'Loaded' : 'Refreshed'}{' '}
                                {refreshMetrics.completed} out of {refreshMetrics.total}
                            </>
                        ) : (
                            <>
                                {shouldUseDashboardLogic && dashboardLoadData?.action === 'initial_load'
                                    ? 'Loading'
                                    : 'Refreshing'}
                                ...
                            </>
                        )}
                    </>
                ) : lastRefresh && dayjs().diff(dayjs(lastRefresh), 'hour') < 24 ? (
                    <div className="flex items-center gap-1">
                        <span>Last refreshed</span>
                        <TZLabel time={lastRefresh} />
                    </div>
                ) : (
                    'Refresh'
                )}
            </span>
        </LemonButton>
    )
}
