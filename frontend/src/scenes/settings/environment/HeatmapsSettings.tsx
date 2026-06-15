import { useActions } from 'kea'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'

import { TeamSettingToggle } from '../components/TeamSettingToggle'

export function HeatmapsSettings(): JSX.Element {
    const { reportHeatmapsToggled } = useActions(eventUsageLogic)
    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })

    return (
        <TeamSettingToggle
            field="heatmaps_opt_in"
            label="Enable heatmaps for web"
            onChange={reportHeatmapsToggled}
            disabledReason={restrictedReason}
        />
    )
}
