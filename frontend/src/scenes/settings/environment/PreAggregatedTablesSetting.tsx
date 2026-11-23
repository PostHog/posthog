import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { Button, Switch } from '@posthog/quill'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonSwitch } from 'lib/lemon-ui/LemonSwitch'
import { teamLogic } from 'scenes/teamLogic'

export function PreAggregatedTablesSetting(): JSX.Element {
    const { updateCurrentTeam } = useActions(teamLogic)
    const { currentTeam } = useValues(teamLogic)
    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    const savedSetting = currentTeam?.modifiers?.useWebAnalyticsPreAggregatedTables
    const [useWebAnalyticsPreAggregatedTables, setUseWebAnalyticsPreAggregatedTables] = useState<boolean>(
        savedSetting ?? false
    )

    const handleChange = (mode: boolean): void => {
        updateCurrentTeam({ modifiers: { ...currentTeam?.modifiers, useWebAnalyticsPreAggregatedTables: mode } })
    }

    const saveDisabledReason =
        useWebAnalyticsPreAggregatedTables === savedSetting ? 'No changes to save' : restrictedReason

    if (todayRailNav) {
        return (
            <div className="flex flex-col items-start gap-4">
                <Switch
                    aria-label="Pre-aggregated tables"
                    checked={useWebAnalyticsPreAggregatedTables}
                    onCheckedChange={setUseWebAnalyticsPreAggregatedTables}
                    disabledReason={restrictedReason}
                />
                <Button
                    variant="primary"
                    onClick={() => handleChange(useWebAnalyticsPreAggregatedTables)}
                    disabledReason={saveDisabledReason}
                >
                    Save
                </Button>
            </div>
        )
    }

    return (
        <>
            <LemonSwitch
                checked={useWebAnalyticsPreAggregatedTables}
                onChange={(newValue) => setUseWebAnalyticsPreAggregatedTables(newValue)}
                disabledReason={restrictedReason}
            />
            <div className="mt-4">
                <LemonButton
                    type="primary"
                    onClick={() => handleChange(useWebAnalyticsPreAggregatedTables)}
                    disabledReason={saveDisabledReason}
                >
                    Save
                </LemonButton>
            </div>
        </>
    )
}
