import { useActions, useValues } from 'kea'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonRadio, LemonRadioOption } from 'lib/lemon-ui/LemonRadio'
import { useState } from 'react'
import { teamLogic } from 'scenes/teamLogic'

const bounceRatePageViewModeOptions: LemonRadioOption<1 | 0>[] = [
    {
        value: 1,
        label: (
            <>
                <div>Enabled</div>
            </>
        ),
    },
    {
        value: 0,
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

    const savedSetting = currentTeam?.cookieless_server_hash_opt_in ? 1 : 0
    const [setting, setSetting] = useState<1 | 0>(savedSetting)

    const handleChange = (newSetting: 1 | 0): void => {
        updateCurrentTeam({ cookieless_server_hash_opt_in: !!newSetting })
    }

    return (
        <>
            <p>
                Use a cookieless server-side hash mode to hash user data. This is an experimental feature preview and
                may result in dropped events.
            </p>
            <LemonRadio value={setting} onChange={setSetting} options={bounceRatePageViewModeOptions} />
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
