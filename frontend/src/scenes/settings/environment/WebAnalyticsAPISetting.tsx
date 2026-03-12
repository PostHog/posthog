import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { LemonSwitch } from '@posthog/lemon-ui'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { teamLogic } from 'scenes/teamLogic'

export function WebAnalyticsEnablePreAggregatedTables(): JSX.Element {
    const { updateCurrentTeam } = useActions(teamLogic)
    const { currentTeam } = useValues(teamLogic)
    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })

    const savedSetting = currentTeam?.web_analytics_pre_aggregated_tables_enabled
    const [enableNewQueryEngine, setEnableNewQueryEngine] = useState<boolean>(savedSetting ?? false)

    const handleSave = (): void => {
        updateCurrentTeam({ web_analytics_pre_aggregated_tables_enabled: enableNewQueryEngine })
    }

    return (
        <>
            <LemonSwitch
                checked={enableNewQueryEngine}
                onChange={(enabled) => setEnableNewQueryEngine(enabled)}
                disabledReason={restrictedReason}
            />
            <div className="mt-4">
                <LemonButton
                    type="primary"
                    onClick={handleSave}
                    disabledReason={enableNewQueryEngine === savedSetting ? 'No changes to save' : restrictedReason}
                >
                    Save
                </LemonButton>
            </div>
        </>
    )
}
