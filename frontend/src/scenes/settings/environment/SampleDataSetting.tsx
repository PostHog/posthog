import { useActions, useValues } from 'kea'

import { LemonSwitch } from '@posthog/lemon-ui'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'
import { SAMPLE_DATA_OPT_OUT_SETTING } from 'scenes/insights/EmptyStates/sampleDataStateLogic'
import { teamLogic } from 'scenes/teamLogic'

export function SampleDataSetting(): JSX.Element {
    const { updateCurrentTeam } = useActions(teamLogic)
    const { currentTeam, currentTeamLoading } = useValues(teamLogic)
    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })

    const checked = currentTeam?.extra_settings?.[SAMPLE_DATA_OPT_OUT_SETTING] !== true

    return (
        <LemonSwitch
            onChange={(newChecked) => {
                updateCurrentTeam({
                    extra_settings: {
                        ...currentTeam?.extra_settings,
                        [SAMPLE_DATA_OPT_OUT_SETTING]: !newChecked,
                    },
                })
            }}
            checked={checked}
            loading={currentTeamLoading}
            disabledReason={restrictedReason}
            label="Show sample charts before the first event"
            data-attr="sample-data-placeholder-switch"
            bordered
        />
    )
}
