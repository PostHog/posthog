import { useActions, useValues } from 'kea'

import { LemonSwitch } from '@posthog/lemon-ui'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { teamLogic } from 'scenes/teamLogic'

import { QuillSettingSwitch } from '../components/QuillSettingSwitch'

export function PersonLastSeenAtEnabled(): JSX.Element {
    const { updateCurrentTeam } = useActions(teamLogic)
    const { currentTeam, currentTeamLoading } = useValues(teamLogic)
    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    const checked = currentTeam?.extra_settings?.person_last_seen_at_enabled === true

    const handleChange = (newChecked: boolean): void => {
        updateCurrentTeam({
            extra_settings: {
                ...currentTeam?.extra_settings,
                person_last_seen_at_enabled: newChecked,
            },
        })
    }

    if (todayRailNav) {
        return (
            <QuillSettingSwitch
                label="Track when a person was last seen"
                checked={checked}
                onCheckedChange={handleChange}
                disabled={currentTeamLoading}
                disabledReason={restrictedReason}
            />
        )
    }

    return (
        <LemonSwitch
            onChange={handleChange}
            checked={checked}
            loading={currentTeamLoading}
            disabledReason={restrictedReason}
            label="Track when a person was last seen"
            bordered
        />
    )
}
