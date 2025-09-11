import { useActions, useValues } from 'kea'
import { useState } from 'react'

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

    const savedSetting = currentTeam?.cookieless_server_hash_mode ?? CookielessServerHashMode.Disabled
    const [setting, setSetting] = useState<CookielessServerHashMode>(savedSetting)

    const handleChange = (newSetting: CookielessServerHashMode): void => {
        updateCurrentTeam({ cookieless_server_hash_mode: newSetting })
    }

    const optionsToShow = options.filter(
        (option) => optionsToShowByDefault.includes(option.value) || option.value === setting
    )

    return (
        <>
            <p>
                Enable cookieless tracking, using a privacy-preserving hash to count unique users without cookies. You
                must enable this here before enabling cookieless in posthog-js, otherwise your events will be dropped.
            </p>
            <LemonRadio value={setting} onChange={setSetting} options={optionsToShow} />
            <div className="mt-4">
                <LemonButton
                    type="primary"
                    onClick={() => handleChange(setting)}
                    disabledReason={setting === savedSetting ? 'No changes to save' : undefined}
                >
                    Save
                </LemonButton>
            </div>
        </>
    )
}
