import React from 'react'
import { useValues } from 'kea'
import { Switch } from 'antd'
import { userLogic } from 'scenes/userLogic'
import api from 'lib/api'

export function IPCapture() {
    const { user } = useValues(userLogic)

    return (
        <div>
            <Switch
                onChange={(checked) => {
                    api.update('api/team/@current', { anonymize_ips: checked })
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
