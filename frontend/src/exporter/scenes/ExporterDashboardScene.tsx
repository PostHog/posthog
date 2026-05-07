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
    // CONTRACT: this mount must share its kea key with the inner <Dashboard>
    // component below. dashboardLogic is keyed by `id`, so as long as both
    // mount with the same id (and compatible placement) they resolve to the
    // same logic instance and the cached branch wins. If a future refactor
    // gives the inner <Dashboard> a different placement key, two distinct
    // logic instances are created — the inner one mounts without `dashboard`,
    // afterMount calls loadDashboard, and shared mode 401s. That was commit 11
    // of #57853.
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
