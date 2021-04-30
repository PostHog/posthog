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
                // @ts-expect-error - id works just fine despite not being in CompoundedComponent
                id="anonymize-ip"
                onChange={(checked) => {
                    updateCurrentTeam({ anonymize_ips: checked })
                }}
                checked={currentTeam?.anonymize_ips}
                loading={currentTeamLoading}
                disabled={currentTeamLoading}
            />
            <label
                style={{
                    marginLeft: '10px',
                }}
                htmlFor="anonymize-ip"
            >
                Discard client IP data
            </label>
        </div>
    )
}
