import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { LemonBanner } from '@posthog/lemon-ui'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonRadio, LemonRadioOption } from 'lib/lemon-ui/LemonRadio'
import { teamLogic } from 'scenes/teamLogic'

import { CookielessServerHashMode } from '~/types'

const options: LemonRadioOption<CookielessServerHashMode>[] = [
    {
        value: CookielessServerHashMode.Stateful,
        label: (
            <>
                <div>Enabled</div>
            </>
        ),
    },
    {
        value: CookielessServerHashMode.Stateless,
        label: (
            <>
                <div>Stateless</div>
            </>
        ),
    },
    {
        value: CookielessServerHashMode.Disabled,
        label: (
            <>
                <div>Disabled</div>
            </>
        ),
    },
]

const optionsToShowByDefault = [CookielessServerHashMode.Stateful, CookielessServerHashMode.Disabled]

export function CookielessServerHashModeSetting(): JSX.Element {
    const { updateCurrentTeam } = useActions(teamLogic)
    const { currentTeam } = useValues(teamLogic)
    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })

    const savedSetting = currentTeam?.cookieless_server_hash_mode ?? CookielessServerHashMode.Disabled
    const [setting, setSetting] = useState<CookielessServerHashMode>(savedSetting)

    const handleChange = (newSetting: CookielessServerHashMode): void => {
        updateCurrentTeam({ cookieless_server_hash_mode: newSetting })
    }

    const optionsToShow = options
        .filter((option) => optionsToShowByDefault.includes(option.value) || option.value === setting)
        .map((option) => ({ ...option, disabledReason: restrictedReason ?? undefined }))

    return (
        <>
            <LemonBanner type="info" className="mb-4">
                When Cookieless server hash mode is enabled, IP-based transformations like GeoIP enrichment and bot
                detection will not enrich events. The IP is hashed into the distinct ID and stripped before
                transformations run.
            </LemonBanner>
            <LemonRadio value={setting} onChange={setSetting} options={optionsToShow} />
            <div className="mt-4">
                <LemonButton
                    type="primary"
                    onClick={() => handleChange(setting)}
                    disabledReason={setting === savedSetting ? 'No changes to save' : restrictedReason}
                >
                    Save
                </LemonButton>
            </div>
        </>
    )
}
