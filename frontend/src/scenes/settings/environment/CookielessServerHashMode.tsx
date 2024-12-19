import { useActions, useValues } from 'kea'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonRadio, LemonRadioOption } from 'lib/lemon-ui/LemonRadio'
import { useState } from 'react'
import { teamLogic } from 'scenes/teamLogic'

import { CookielessServerHashMode } from '~/types'

const options: LemonRadioOption<CookielessServerHashMode>[] = [
    {
        value: CookielessServerHashMode.Stateful,
        label: (
            <>
                <div>Stateful</div>
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

export function CookielessServerHashModeSetting(): JSX.Element {
    const { updateCurrentTeam } = useActions(teamLogic)
    const { currentTeam } = useValues(teamLogic)

    const savedSetting = currentTeam?.cookieless_server_hash_mode ?? CookielessServerHashMode.Disabled
    const [setting, setSetting] = useState<CookielessServerHashMode>(savedSetting)

    const handleChange = (newSetting: CookielessServerHashMode): void => {
        updateCurrentTeam({ cookieless_server_hash_mode: newSetting })
    }

    return (
        <>
            <p>
                Use a cookieless server-side hash mode to hash user data. This is an experimental feature preview and
                may result in dropped events.
            </p>
            <LemonRadio value={setting} onChange={setSetting} options={options} />
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
