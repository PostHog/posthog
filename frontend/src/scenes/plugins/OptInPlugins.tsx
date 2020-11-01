import React from 'react'
import { useActions, useValues } from 'kea'
import { Switch } from 'antd'
import { userLogic } from 'scenes/userLogic'

export function OptInPlugins(): JSX.Element {
    const { userUpdateRequest } = useActions(userLogic)
    const { user } = useValues(userLogic)

    return (
        <div>
            <Switch
                onChange={(checked) => {
                    userUpdateRequest({ team: { plugins_opt_in: checked } })
                }}
                defaultChecked={user?.team?.plugins_opt_in}
            />
            <label
                style={{
                    marginLeft: '10px',
                }}
            >
                Enable plugins for this project
            </label>
        </div>
    )
}
