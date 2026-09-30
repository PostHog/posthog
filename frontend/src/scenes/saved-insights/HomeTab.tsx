import { useValues } from 'kea'
import posthog from 'posthog-js'
import type { ReactNode } from 'react'

import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { Dashboard } from 'scenes/dashboard/Dashboard'
import { newDashboardLogic } from 'scenes/dashboard/newDashboardLogic'
import { teamLogic } from 'scenes/teamLogic'

import { DashboardPlacement } from '~/types'

import { HomeTabDefault } from './HomeTabDefault'

export function HomeTab({ dashboardActions }: { dashboardActions?: ReactNode }): JSX.Element {
    const { currentTeam, currentTeamLoading } = useValues(teamLogic)
    const { isLoading: dashboardCreationLoading } = useValues(newDashboardLogic)
    const homeDashboardLoadingLabel = dashboardCreationLoading
        ? 'Creating your Home dashboard'
        : 'Updating your Home dashboard'

    useOnMountEffect(() => {
        posthog.capture('product analytics home viewed')
    })

    if (!currentTeam && currentTeamLoading) {
        return (
            <div className="flex min-h-80 flex-col gap-3 py-3" aria-label="Loading product analytics Home">
                <LemonSkeleton.Row repeat={3} />
            </div>
        )
    }

    return (
        <div className="@container/home-tab pb-4 @min-[48rem]/saved-insights:py-3">
            {dashboardCreationLoading || currentTeamLoading ? (
                <div
                    className="flex min-h-80 flex-col gap-3 py-3"
                    role="status"
                    aria-live="polite"
                    aria-label={homeDashboardLoadingLabel}
                >
                    <div className="font-semibold">{homeDashboardLoadingLabel}…</div>
                    <LemonSkeleton.Row repeat={3} />
                </div>
            ) : currentTeam?.home_tab_dashboard ? (
                <div className="-mt-8">
                    <Dashboard id={String(currentTeam.home_tab_dashboard)} placement={DashboardPlacement.Builtin} />
                </div>
            ) : (
                <HomeTabDefault dashboardActions={dashboardActions} />
            )}
        </div>
    )
}
