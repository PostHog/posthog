import React from 'react'
import { SessionRecordingsTable } from './SessionRecordingsTable'
import { PageHeader } from 'lib/components/PageHeader'
import { Typography } from 'antd'
import { teamLogic } from 'scenes/teamLogic'
import { useValues } from 'kea'

export function Sessions(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    return (
        <div>
            <PageHeader title="Session Recordings" />
            {currentTeam?.session_recording_opt_in ? (
                <div className="sessions-wrapper">
                    <div className="sessions-with-filters">
                        <SessionRecordingsTable key="global" />
                    </div>
                </div>
            ) : (
                <div>
                    <Typography.Text>Please enable session recording....</Typography.Text>
                </div>
            )}
        </div>
    )
}
