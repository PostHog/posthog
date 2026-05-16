import posthog from 'posthog-js'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'

import { TeamSettingToggle } from '../components/TeamSettingToggle'

export function FrustrationDetectionSettings(): JSX.Element {
    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })

    return (
        <TeamSettingToggle
            field="frustration_detection_enabled"
            label="Enable automatic frustration detection"
            onChange={(checked) => posthog.capture('frustration_detection_toggled', { isEnabled: checked })}
            disabledReason={restrictedReason}
        />
    )
}
