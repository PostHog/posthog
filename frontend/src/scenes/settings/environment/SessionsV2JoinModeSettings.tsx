import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonRadio, LemonRadioOption } from 'lib/lemon-ui/LemonRadio'
import { teamLogic } from 'scenes/teamLogic'

import { HogQLQueryModifiers } from '~/queries/schema/schema-general'

type SessionsV2JoinMode = NonNullable<HogQLQueryModifiers['sessionsV2JoinMode']>

const options: LemonRadioOption<SessionsV2JoinMode>[] = [
    {
        value: 'string',
        label: (
            <>
                <div>String</div>
            </>
        ),
    },
    {
        value: 'uuid',
        label: (
            <>
                <div>UUID</div>
            </>
        ),
    },
]

export function SessionsV2JoinModeSettings(): JSX.Element {
    const { updateCurrentTeam } = useActions(teamLogic)
    const { currentTeam } = useValues(teamLogic)

    const savedSessionTableVersion =
        currentTeam?.modifiers?.sessionsV2JoinMode ?? currentTeam?.default_modifiers?.sessionsV2JoinMode ?? 'string'
    const [sessionsV2JoinMode, setSessionsV2JoinMode] = useState<SessionsV2JoinMode>(savedSessionTableVersion)

    const handleChange = (version: SessionsV2JoinMode): void => {
        updateCurrentTeam({ modifiers: { ...currentTeam?.modifiers, sessionsV2JoinMode: version } })
    }

    return (
        <>
            <p>Choose which version join mode to use. Don't set this unless you know what you're doing.</p>
            <LemonRadio value={sessionsV2JoinMode} onChange={setSessionsV2JoinMode} options={options} />
            <div className="mt-4">
                <LemonButton
                    type="primary"
                    onClick={() => handleChange(sessionsV2JoinMode)}
                    disabledReason={sessionsV2JoinMode === savedSessionTableVersion ? 'No changes to save' : undefined}
                >
                    Save
                </LemonButton>
            </div>
        </>
    )
}
