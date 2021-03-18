import { Select, Skeleton } from 'antd'
import { useActions, useValues } from 'kea'
import React from 'react'
import { preflightLogic } from 'scenes/PreflightCheck/logic'
import { teamLogic } from 'scenes/teamLogic'

export function TimezoneConfig(): JSX.Element {
    const { preflight } = useValues(preflightLogic)
    const { currentTeam, currentTeamLoading } = useValues(teamLogic)
    const { patchCurrentTeam } = useActions(teamLogic)

    if (!preflight || !currentTeam) {
        return <Skeleton paragraph={{ rows: 0 }} active />
    }

    return (
        <div>
            <Select
                showSearch
                placeholder="Select a timezone"
                style={{ width: '40rem', maxWidth: '100%' }}
                loading={currentTeamLoading}
                value={currentTeam.timezone}
                onChange={(val) => patchCurrentTeam({ timezone: val })}
            >
                {preflight.available_timezones.map((tz) => (
                    <Select.Option value={tz} key={tz}>
                        {tz}
                    </Select.Option>
                ))}
            </Select>
            ,
        </div>
    )
}
