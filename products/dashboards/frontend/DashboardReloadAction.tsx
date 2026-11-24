import { useActions, useValues } from 'kea'

import { DashboardRefreshButton } from 'lib/components/DashboardRefreshButton/DashboardRefreshButton'
import { DashboardRefreshProgress } from 'lib/components/DashboardRefreshButton/DashboardRefreshProgress'
import { TZLabel } from 'lib/components/TZLabel'
import { dayjs } from 'lib/dayjs'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { usePageVisibilityCb } from 'lib/hooks/usePageVisibility'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import { Scene } from 'scenes/sceneTypes'

import { DashboardActivitySummary } from './DashboardActivitySummary'
import { QuillLastRefreshText } from './QuillLastRefreshText'

export const LastRefreshText = (): JSX.Element => {
    const { effectiveLastRefresh } = useValues(dashboardLogic)
    return (
        <div className="flex items-center gap-1">
            {effectiveLastRefresh && dayjs().diff(dayjs(effectiveLastRefresh), 'hour') < 24 && (
                <div className="flex items-center gap-1">
                    <span>Last refreshed</span>
                    <TZLabel time={effectiveLastRefresh} />
                </div>
            )}
        </div>
    )
}

function DashboardLogicRefreshProgress(): JSX.Element {
    const { refreshMetrics, dashboardLoadData } = useValues(dashboardLogic)
    const initialLoad =
        dashboardLoadData?.action === 'initial_load' || dashboardLoadData?.action === 'initial_load_with_variables'
    return (
        <DashboardRefreshProgress
            completed={refreshMetrics.completed}
            total={refreshMetrics.total}
            initialLoad={initialLoad}
        />
    )
}

/** Loading / progress / pessimistic last refresh — same as the left side of `DashboardReloadAction`, without refresh controls. */
export function DashboardRefreshStatusText(): JSX.Element {
    const { itemsLoading } = useValues(dashboardLogic)
    return (
        <span className="text-muted text-sm whitespace-nowrap">
            {itemsLoading ? <DashboardLogicRefreshProgress /> : <LastRefreshText />}
        </span>
    )
}

export function DashboardReloadAction(): JSX.Element {
    const { dashboard, itemsLoading, autoRefresh, blockRefresh, nextAllowedDashboardRefresh, effectiveLastRefresh } =
        useValues(dashboardLogic)
    const { triggerDashboardRefresh, setAutoRefresh, setPageVisibility, cancelDashboardRefresh } =
        useActions(dashboardLogic)
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    usePageVisibilityCb(setPageVisibility)

    const upToDateReason =
        !itemsLoading &&
        blockRefresh &&
        nextAllowedDashboardRefresh &&
        dayjs(nextAllowedDashboardRefresh).isAfter(dayjs())
            ? `Next bulk refresh possible ${dayjs(nextAllowedDashboardRefresh).fromNow()}`
            : undefined
    const refreshButton = (
        <DashboardRefreshButton
            loading={itemsLoading}
            onRefresh={triggerDashboardRefresh}
            onCancel={cancelDashboardRefresh}
            upToDateReason={upToDateReason}
            autoRefresh={{ ...autoRefresh, onChange: setAutoRefresh }}
            lastRefresh={effectiveLastRefresh}
            // pinned: data-attr values feed autocapture dashboards
            dataAttr="dashboard-items-action-refresh"
            shortcutName="DashboardRefresh"
            shortcutScope={Scene.Dashboard}
        />
    )

    const activitySummary = dashboard && (
        <DashboardActivitySummary
            dashboardId={dashboard.id}
            createdAt={dashboard.created_at}
            createdBy={dashboard.created_by}
        />
    )

    if (todayRailNav) {
        return (
            <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 sm:flex-nowrap">
                {activitySummary}
                {itemsLoading ? (
                    <DashboardLogicRefreshProgress />
                ) : (
                    <QuillLastRefreshText className="@max-5xl/dashboard-filters:hidden" />
                )}
                {refreshButton}
            </div>
        )
    }

    return (
        <div className="relative flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 sm:flex-nowrap">
            {activitySummary}
            <DashboardRefreshStatusText />
            {refreshButton}
        </div>
    )
}
