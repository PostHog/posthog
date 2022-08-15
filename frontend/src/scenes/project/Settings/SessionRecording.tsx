import React from 'react'
import { useActions, useValues } from 'kea'
import { Switch } from 'antd'
import { teamLogic } from 'scenes/teamLogic'

export function SessionRecording(): JSX.Element {
    const { updateCurrentTeam } = useActions(teamLogic)
    const { currentTeam } = useValues(teamLogic)

    return (
        <div style={{ marginBottom: 16 }}>
            <div style={{ marginBottom: 8 }}>
                <Switch
                    id="opt-in-session-recording-switch"
                    data-attr="opt-in-session-recording-switch"
                    onChange={(checked) => {
                        updateCurrentTeam({ session_recording_opt_in: checked })
                    }}
                    checked={currentTeam?.session_recording_opt_in}
                />
                <label
                    style={{
                        marginLeft: '10px',
                    }}
                    htmlFor="opt-in-session-recording-switch"
                >
                    Record user sessions on Authorized URLs
                </label>
            </div>
        </div>
    )
}
