import { Select, Skeleton } from 'antd'
import { useActions, useValues } from 'kea'
import React from 'react'
import { preflightLogic } from 'scenes/PreflightCheck/logic'
import { teamLogic } from 'scenes/teamLogic'

export function TimezoneConfig(): JSX.Element {
    const { preflight } = useValues(preflightLogic)
    const { currentTeam, currentTeamLoading } = useValues(teamLogic)
    const { updateCurrentTeam } = useActions(teamLogic)

    if (!preflight?.available_timezones || !currentTeam) {
        return <Skeleton paragraph={{ rows: 0 }} active />
    }

    return (
        <div>
            <Select
                showSearch
                placeholder="Select a timezone"
                style={{ width: '20rem', maxWidth: '100%' }}
                loading={currentTeamLoading}
                disabled={currentTeamLoading}
                value={currentTeam.timezone}
                onChange={(val) => updateCurrentTeam({ timezone: val })}
                data-attr="timezone-select"
            >
                {Object.entries(preflight.available_timezones).map(([tz, offset]) => {
                    const display = `${tz.replace(/\//g, ' / ').replace(/_/g, ' ')} (UTC${
                        offset > 0 ? '+' : '-'
                    }${Math.abs(offset)})`
                    return (
                        <Select.Option value={tz} key={tz}>
                            {display}
                        </Select.Option>
                    )
                })}
            </Select>
        </div>
    )
}
