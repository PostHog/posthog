import React from 'react'
import { useActions, useValues } from 'kea'
import { Switch } from 'antd'
import { teamLogic } from 'scenes/teamLogic'

export function IPCapture(): JSX.Element {
    const { updateCurrentTeam } = useActions(teamLogic)
    const { currentTeam, currentTeamLoading } = useValues(teamLogic)

    return (
        <div>
            <Switch
                onChange={(checked) => {
                    updateCurrentTeam({ anonymize_ips: checked })
                }}
                defaultChecked={currentTeam?.anonymize_ips}
                loading={currentTeamLoading}
                disabled={currentTeamLoading}
            />
            <label
                style={{
                    marginLeft: '10px',
                }}
            >
                Discard client IP data
            </label>
        </div>
    )
}
