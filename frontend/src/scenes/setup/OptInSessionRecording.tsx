import React from 'react'
import { useActions, useValues } from 'kea'
import { userLogic } from '../userLogic'
import { Switch } from 'antd'

export function OptInSessionRecording(): JSX.Element {
    const { userUpdateRequest } = useActions(userLogic)
    const { user } = useValues(userLogic)

    return (
        <div>
            <Switch
                onChange={(checked) => {
                    userUpdateRequest({ team: { session_recording_opt_in: checked } })
                }}
                defaultChecked={user!.team.session_recording_opt_in}
            />
            <label
                style={{
                    marginLeft: '10px',
                }}
            >
                Record user sessions
            </label>
        </div>
    )
}
