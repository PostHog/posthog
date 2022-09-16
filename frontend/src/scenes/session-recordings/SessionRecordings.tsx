import React from 'react'
import { SessionRecordingsTable } from './SessionRecordingsTable'
import { PageHeader } from 'lib/components/PageHeader'
import { teamLogic } from 'scenes/teamLogic'
import { useValues } from 'kea'
import { urls } from 'scenes/urls'
import { SceneExport } from 'scenes/sceneTypes'
import { sessionRecordingsTableLogic } from 'scenes/session-recordings/sessionRecordingsTableLogic'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { SessionRecordingsPlaylist } from './SessionRecordingsPlaylist'
import { SessionRecordingsFilters } from './filters/SessionRecordingFilters'
import { AlertMessage } from 'lib/components/AlertMessage'
import { Link } from '@posthog/lemon-ui'
import { SessionRecordingsEventFilters } from './filters/SessionRecordingEventFilters'

export function SessionsRecordings(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    return (
        <div>
            <PageHeader title={<div>Recordings</div>} />
            {currentTeam && !currentTeam?.session_recording_opt_in ? (
                <div className="mb-4">
                    <AlertMessage type="info">
                        Session recordings are currently disabled for this project. To use this feature, please go to
                        your <Link to={`${urls.projectSettings()}#recordings`}>project settings</Link> and enable it.
                    </AlertMessage>
                </div>
            ) : null}
            <SessionRecordingsFilters />
            {featureFlags[FEATURE_FLAGS.SESSION_RECORDINGS_PLAYLIST] ? (
                <SessionRecordingsPlaylist key="global" />
            ) : (
                <div className="space-y-4">
                    <div style={{ maxWidth: 700 }}>
                        <SessionRecordingsEventFilters />
                    </div>
                    <SessionRecordingsTable key="global" />
                </div>
            )}
        </div>
    )
}

export const scene: SceneExport = {
    component: SessionsRecordings,
    logic: sessionRecordingsTableLogic,
}
