import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'

import { TeamSettingToggle } from '../components/TeamSettingToggle'

export function IPCapture(): JSX.Element {
    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })

    return <TeamSettingToggle field="anonymize_ips" label="Discard client IP data" disabledReason={restrictedReason} />
}
