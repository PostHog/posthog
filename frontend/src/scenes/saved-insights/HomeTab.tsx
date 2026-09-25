import { useValues } from 'kea'
import posthog from 'posthog-js'

import { Spinner } from '@posthog/lemon-ui'

import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { Dashboard } from 'scenes/dashboard/Dashboard'
import { teamLogic } from 'scenes/teamLogic'

import { DashboardPlacement } from '~/types'

import { HomeTabTemplatePicker } from './HomeTabTemplatePicker'

export function HomeTab(): JSX.Element {
    const { currentTeam, currentTeamLoading } = useValues(teamLogic)

    useOnMountEffect(() => {
        posthog.capture('product analytics home viewed')
    })

    if (!currentTeam && currentTeamLoading) {
        return (
            <div className="flex justify-center py-12">
                <Spinner textColored captureTime />
            </div>
        )
    }

    if (currentTeam?.home_tab_dashboard) {
        return (
            <Dashboard
                id={String(currentTeam.home_tab_dashboard)}
                placement={DashboardPlacement.Builtin}
                requireExplicitEditMode
            />
        )
    }

    return <HomeTabTemplatePicker />
}
