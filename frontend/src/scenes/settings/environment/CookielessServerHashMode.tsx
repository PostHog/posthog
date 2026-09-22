import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { LemonBanner, LemonSwitch } from '@posthog/lemon-ui'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { teamLogic } from 'scenes/teamLogic'

import { CookielessServerHashMode } from '~/types'

export function CookielessServerHashModeSetting(): JSX.Element {
    const { updateCurrentTeam } = useActions(teamLogic)
    const { currentTeam } = useValues(teamLogic)
    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })

    const savedEnabled =
        (currentTeam?.cookieless_server_hash_mode ?? CookielessServerHashMode.Disabled) !==
        CookielessServerHashMode.Disabled
    const [enabled, setEnabled] = useState<boolean>(savedEnabled)

    const handleSave = (): void => {
        updateCurrentTeam({
            cookieless_server_hash_mode: enabled
                ? CookielessServerHashMode.Stateful
                : CookielessServerHashMode.Disabled,
        })
    }

    return (
        <>
            <LemonBanner type="info" className="mb-4">
                When cookieless tracking is enabled, the IP address is hashed into the distinct ID and stripped before
                transformations run, so IP-based transformations like GeoIP enrichment and bot detection will not enrich
                those events.
            </LemonBanner>
            <LemonSwitch
                label="Enable cookieless tracking"
                checked={enabled}
                onChange={setEnabled}
                disabledReason={restrictedReason}
                data-attr="cookieless-tracking-toggle"
            />
            <div className="mt-4">
                <LemonButton
                    type="primary"
                    onClick={handleSave}
                    disabledReason={enabled === savedEnabled ? 'No changes to save' : restrictedReason}
                >
                    Save
                </LemonButton>
            </div>
        </>
    )
}
