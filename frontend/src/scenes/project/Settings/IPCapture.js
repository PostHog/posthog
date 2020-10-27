import React from 'react'
import { useActions, useValues } from 'kea'
import { Switch } from 'antd'
import { userLogic } from 'scenes/userLogic'

export function IPCapture() {
    const { userUpdateRequest } = useActions(userLogic)
    const { user } = useValues(userLogic)

    return (
        <div>
            <Switch
                onChange={(checked) => {
                    userUpdateRequest({ team: { anonymize_ips: checked } })
                }}
                defaultChecked={user.team.anonymize_ips}
            />
            <label
                style={{
                    marginLeft: '10px',
                }}
            >
                Anonymize client IP data
            </label>
        </div>
    )
}
