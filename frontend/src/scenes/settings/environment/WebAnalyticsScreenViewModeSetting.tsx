import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonRadio, LemonRadioOption } from 'lib/lemon-ui/LemonRadio'
import { teamLogic } from 'scenes/teamLogic'
import { WebAnalyticsScreenViewMode } from 'scenes/web-analytics/screenViewMode'

const SCREEN_VIEW_MODE_OPTIONS: LemonRadioOption<WebAnalyticsScreenViewMode>[] = [
    {
        value: 'pageviews',
        label: (
            <>
                <div>Pageviews only</div>
                <div className="text-secondary">
                    Counts <code>$pageview</code> events. The Paths table lists each <code>$pathname</code>.
                </div>
            </>
        ),
    },
    {
        value: 'screens',
        label: (
            <>
                <div>Screen views only</div>
                <div className="text-secondary">
                    Counts <code>$screen</code> events from mobile apps. The Paths table lists each{' '}
                    <code>$screen_name</code>.
                </div>
            </>
        ),
    },
    {
        value: 'pageviews_and_screens',
        label: (
            <>
                <div>Pageviews and screen views</div>
                <div className="text-secondary">
                    Counts both events. Screen views have no <code>$pathname</code>, so the Paths table lists their{' '}
                    <code>$screen_name</code> instead.
                </div>
            </>
        ),
    },
]

export function WebAnalyticsScreenViewModeSetting(): JSX.Element {
    const { updateCurrentTeam } = useActions(teamLogic)
    const { currentTeam, currentTeamLoading } = useValues(teamLogic)
    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })

    const savedMode = currentTeam?.modifiers?.webAnalyticsScreenViewMode ?? null
    const [mode, setMode] = useState<WebAnalyticsScreenViewMode | null>(savedMode)

    return (
        <>
            {savedMode === null && (
                <p className="text-secondary">
                    No option is selected yet. Totals count both events, and the Paths table only lists events with a{' '}
                    <code>$pathname</code>.
                </p>
            )}
            <LemonRadio
                value={mode ?? undefined}
                onChange={setMode}
                options={SCREEN_VIEW_MODE_OPTIONS.map((o) => ({ ...o, disabledReason: restrictedReason ?? undefined }))}
            />
            <div className="mt-4">
                <LemonButton
                    type="primary"
                    data-attr="web-analytics-screen-view-mode-save"
                    loading={currentTeamLoading}
                    onClick={() =>
                        mode &&
                        updateCurrentTeam({
                            modifiers: { ...currentTeam?.modifiers, webAnalyticsScreenViewMode: mode },
                        })
                    }
                    disabledReason={!mode || mode === savedMode ? 'No changes to save' : restrictedReason}
                >
                    Save
                </LemonButton>
            </div>
        </>
    )
}
