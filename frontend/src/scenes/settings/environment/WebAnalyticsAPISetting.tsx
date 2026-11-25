import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { LemonSwitch } from '@posthog/lemon-ui'
import { Button, Switch } from '@posthog/quill'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { teamLogic } from 'scenes/teamLogic'

export function WebAnalyticsEnablePreAggregatedTables(): JSX.Element {
    const { updateCurrentTeam } = useActions(teamLogic)
    const { currentTeam } = useValues(teamLogic)
    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    const savedSetting = currentTeam?.web_analytics_pre_aggregated_tables_enabled
    const [enableNewQueryEngine, setEnableNewQueryEngine] = useState<boolean>(savedSetting ?? false)

    const handleSave = (): void => {
        updateCurrentTeam({ web_analytics_pre_aggregated_tables_enabled: enableNewQueryEngine })
    }

    const saveDisabledReason = enableNewQueryEngine === savedSetting ? 'No changes to save' : restrictedReason

    if (todayRailNav) {
        return (
            <div className="flex flex-col items-start gap-4">
                <Switch
                    aria-label="New query engine"
                    checked={enableNewQueryEngine}
                    onCheckedChange={setEnableNewQueryEngine}
                    disabledReason={restrictedReason}
                />
                <Button variant="primary" onClick={handleSave} disabledReason={saveDisabledReason}>
                    Save
                </Button>
            </div>
        )
    }

    return (
        <>
            <LemonSwitch
                checked={enableNewQueryEngine}
                onChange={(enabled) => setEnableNewQueryEngine(enabled)}
                disabledReason={restrictedReason}
            />
            <div className="mt-4">
                <LemonButton type="primary" onClick={handleSave} disabledReason={saveDisabledReason}>
                    Save
                </LemonButton>
            </div>
        </>
    )
}
