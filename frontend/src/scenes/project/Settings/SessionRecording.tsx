import React from 'react'
import { useActions, useValues } from 'kea'
import { teamLogic } from 'scenes/teamLogic'
import { LemonSwitch } from '@posthog/lemon-ui'

export function SessionRecording(): JSX.Element {
    const { updateCurrentTeam } = useActions(teamLogic)
    const { currentTeam } = useValues(teamLogic)

    return (
        <LemonSwitch
            data-attr="opt-in-session-recording-switch"
            onChange={(checked) => {
                updateCurrentTeam({ session_recording_opt_in: checked })
            }}
            checked={!!currentTeam?.session_recording_opt_in}
            label="Record user sessions on Authorized URLs"
            bordered
        />
    )
}
