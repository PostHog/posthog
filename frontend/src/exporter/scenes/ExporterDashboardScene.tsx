import { useActions } from 'kea'
import { useCallback, useEffect } from 'react'

import { usePageVisibilityCb } from 'lib/hooks/usePageVisibility'
import { Dashboard } from 'scenes/dashboard/Dashboard'
import { AUTO_REFRESH_INITIAL_INTERVAL_SECONDS } from 'scenes/dashboard/dashboardConstants'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import { scheduleSharedDashboardStaleAutoForceIfEligible } from 'scenes/dashboard/dashboardUtils'

import { getQueryBasedDashboard } from '~/queries/nodes/InsightViz/utils'
import { DashboardPlacement } from '~/types'

import { ExportType, ExportedData } from '../types'

function SharedDashboardAutoRefresh({ dashboardId }: { dashboardId: number }): JSX.Element | null {
    const logic = dashboardLogic({ id: dashboardId, placement: DashboardPlacement.Public })
    const { setAutoRefresh, setPageVisibility, triggerDashboardRefresh } = useActions(logic)

    const onVisibilityChange = useCallback(
        (visible: boolean) => {
            setPageVisibility(visible)
            if (visible) {
                scheduleSharedDashboardStaleAutoForceIfEligible({
                    effectiveLastRefresh: logic.values.effectiveLastRefresh,
                    triggerDashboardRefresh: () => void triggerDashboardRefresh(),
                })
            }
        },
        [setPageVisibility, triggerDashboardRefresh, logic]
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
    return (
        <>
            {type !== ExportType.Image && <SharedDashboardAutoRefresh dashboardId={dashboard.id} />}
            <Dashboard
                id={String(dashboard.id)}
                dashboard={getQueryBasedDashboard(dashboard)!}
                placement={type === ExportType.Image ? DashboardPlacement.Export : DashboardPlacement.Public}
                themes={themes}
            />
        </>
    )
}
