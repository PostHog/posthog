import { useActions } from 'kea'
import { useCallback, useEffect, useMemo } from 'react'

import { usePageVisibilityCb } from 'lib/hooks/usePageVisibility'
import { Dashboard } from 'scenes/dashboard/Dashboard'
import { AUTO_REFRESH_INITIAL_INTERVAL_SECONDS } from 'scenes/dashboard/dashboardConstants'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'

import { getQueryBasedDashboard } from '~/queries/nodes/InsightViz/utils'
import { DashboardPlacement, DashboardType, QueryBasedInsightModel } from '~/types'

import { ExportType, ExportedData } from '../types'

function SharedDashboardAutoRefresh({
    dashboardId,
    dashboard,
}: {
    dashboardId: number
    dashboard: DashboardType<QueryBasedInsightModel>
}): JSX.Element | null {
    // Pass `dashboard` so dashboardLogic.afterMount uses the cached branch
    // (loadDashboardSuccess) instead of firing an unauthenticated loadDashboard.
    //
    // CONTRACT: dashboardLogic is keyed by `id` only. This mount and the
    // inner <Dashboard> below pass the same id, so they resolve to the same
    // logic instance — the first mount's props win and the second is a no-op
    // for prop initialisation. If a future refactor splits the auto-refresh
    // off so it mounts a different keyed instance, the inner <Dashboard>
    // would mount without `dashboard`, afterMount would call loadDashboard,
    // and shared mode would 401. Whichever component mounts first must seed
    // `dashboard` for the cached branch to win.
    const logic = dashboardLogic({ id: dashboardId, placement: DashboardPlacement.Public, dashboard })
    const { setAutoRefresh, setPageVisibility, forceRefreshIfStale } = useActions(logic)

    const onVisibilityChange = useCallback(
        (visible: boolean) => {
            setPageVisibility(visible)
            if (visible) {
                forceRefreshIfStale()
            }
        },
        [setPageVisibility, forceRefreshIfStale]
    )
    usePageVisibilityCb(onVisibilityChange)

    useEffect(() => {
        setAutoRefresh(true, AUTO_REFRESH_INITIAL_INTERVAL_SECONDS)
    }, [setAutoRefresh])

    return null
}

export default function ExporterDashboardScene({
    dashboard,
    type,
    themes,
}: {
    dashboard: NonNullable<ExportedData['dashboard']>
    type: ExportedData['type']
    themes: ExportedData['themes']
}): JSX.Element {
    const queryBasedDashboard = useMemo(() => getQueryBasedDashboard(dashboard)!, [dashboard])
    return (
        <>
            {type !== ExportType.Image && (
                <SharedDashboardAutoRefresh dashboardId={dashboard.id} dashboard={queryBasedDashboard} />
            )}
            <Dashboard
                id={String(dashboard.id)}
                dashboard={queryBasedDashboard}
                placement={type === ExportType.Image ? DashboardPlacement.Export : DashboardPlacement.Public}
                themes={themes}
            />
        </>
    )
}
