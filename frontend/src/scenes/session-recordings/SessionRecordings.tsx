import React from 'react'
import { SessionRecordingsTable } from './SessionRecordingsTable'
import { PageHeader } from 'lib/components/PageHeader'
import { teamLogic } from 'scenes/teamLogic'
import { useValues } from 'kea'
import { SceneExport } from 'scenes/sceneTypes'
import { sessionRecordingsTableLogic } from 'scenes/session-recordings/sessionRecordingsTableLogic'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { SessionRecordingsPlaylist } from './SessionRecordingsPlaylist'
import { SessionRecordingsTopBar } from './filters/SessionRecordingsTopBar'
import { SessionRecordingsFilters } from './filters/SessionRecordingsFilters'
import { SessionRecordingOptInBanner } from 'lib/introductions/SessionRecordingOptInBanner'

export function SessionsRecordings(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const showSessionRecordingOptInPage = currentTeam && !currentTeam?.session_recording_opt_in

    if (showSessionRecordingOptInPage) {
        return (
            <div>
                <PageHeader title={<div>Recordings</div>} />
                <SessionRecordingOptInBanner />
            </div>
        )
    }

    return (
        <div>
            <PageHeader title={<div>Recordings</div>} />
            <SessionRecordingsTopBar />
            {featureFlags[FEATURE_FLAGS.SESSION_RECORDINGS_PLAYER_V3] ? (
                <SessionRecordingsPlaylist key="global" />
            ) : (
                <div className="space-y-4">
                    <div style={{ maxWidth: 700 }}>
                        <SessionRecordingsFilters />
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
