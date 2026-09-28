import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'

import { LemonButton, Spinner } from '@posthog/lemon-ui'

import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { preflightLogic } from 'lib/logic/preflightLogic'
import { Dashboard } from 'scenes/dashboard/Dashboard'
import { teamLogic } from 'scenes/teamLogic'

import { DashboardPlacement } from '~/types'

import { HomeTabTemplatePicker } from './HomeTabTemplatePicker'

export function HomeTab(): JSX.Element {
    const { currentTeam, currentTeamLoading } = useValues(teamLogic)
    const { updateCurrentTeam } = useActions(teamLogic)
    const { preflight } = useValues(preflightLogic)

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
            <>
                {preflight?.is_debug && (
                    <div className="flex justify-end px-4 pt-2">
                        <LemonButton
                            type="tertiary"
                            size="small"
                            loading={currentTeamLoading}
                            disabledReason={currentTeamLoading ? 'Saving…' : undefined}
                            tooltip="Local dev only. Clears the saved template so you can see the picker again."
                            data-attr="home-tab-dev-reset-template"
                            onClick={() => updateCurrentTeam({ home_tab_dashboard: null })}
                        >
                            Reset home tab template (dev)
                        </LemonButton>
                    </div>
                )}
                <Dashboard
                    id={String(currentTeam.home_tab_dashboard)}
                    placement={DashboardPlacement.Builtin}
                    requireExplicitEditMode
                />
            </>
        )
    }

    return <HomeTabTemplatePicker />
}
