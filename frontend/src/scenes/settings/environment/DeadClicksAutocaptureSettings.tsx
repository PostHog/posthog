import posthog from 'posthog-js'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'

import { TeamSettingToggle } from '../components/TeamSettingToggle'

export function DeadClicksAutocaptureSettings(): JSX.Element {
    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })

    return (
        <TeamSettingToggle
            field="capture_dead_clicks"
            label="Enable dead clicks autocapture"
            onChange={(checked) => posthog.capture('dead_clicks_autocapture_toggled', { isEnabled: checked })}
            disabledReason={restrictedReason}
        />
    )
}
