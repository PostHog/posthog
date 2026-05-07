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
    // (loadDashboardSuccess) instead of firing an unauthenticated loadDashboard,
    // matching the props <Dashboard> binds with via BindLogic.
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
