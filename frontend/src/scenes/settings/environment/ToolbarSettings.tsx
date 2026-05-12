import { LemonBanner } from '@posthog/lemon-ui'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'

import { TeamSettingToggle } from '../components/TeamSettingToggle'

export function ToolbarSettings(): JSX.Element {
    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })

    return (
        <div className="flex flex-col gap-3">
            <TeamSettingToggle
                field="toolbar_disabled"
                invert
                label="Enable PostHog Toolbar for this environment"
                disabledReason={restrictedReason}
            />
            <LemonBanner type="info">
                When disabled, the toolbar blocks every OAuth authorize, callback and refresh request from this
                environment, hides all "Open in toolbar" launch points in the UI, and refuses the legacy
                redirect-to-site endpoint. Authorized URLs remain configured so re-enabling later does not require
                re-adding domains.
            </LemonBanner>
        </div>
    )
}
