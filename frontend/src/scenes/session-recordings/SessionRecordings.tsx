import React from 'react'
import { SessionRecordingsTable } from './SessionRecordingsTable'
import { PageHeader } from 'lib/components/PageHeader'
import { teamLogic } from 'scenes/teamLogic'
import { useValues } from 'kea'
import { urls } from 'scenes/urls'
import { SceneExport } from 'scenes/sceneTypes'
import { sessionRecordingsTableLogic } from 'scenes/session-recordings/sessionRecordingsTableLogic'
import { AlertMessage } from 'lib/components/AlertMessage'
import { Link } from '@posthog/lemon-ui'

export function SessionsRecordings(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    return (
        <div>
            <PageHeader title={<div>Recordings</div>} />
            {currentTeam && !currentTeam?.session_recording_opt_in ? (
                <div className="mb-4">
                    <AlertMessage type="info">
                        Session Recordings are currently disabled for this Project. To use this feature, please go to
                        your <Link to={`${urls.projectSettings()}#recordings`}>project settings</Link> and enable it.
                    </AlertMessage>
                </div>
            ) : null}

            <SessionRecordingsTable key="global" />
        </div>
    )
}

export const scene: SceneExport = {
    component: SessionsRecordings,
    logic: sessionRecordingsTableLogic,
}
