import React from 'react'
import { SessionRecordingsTable } from './SessionRecordingsTable'
import { PageHeader } from 'lib/components/PageHeader'
import { Alert, Button, Row } from 'antd'
import { teamLogic } from 'scenes/teamLogic'
import { useValues } from 'kea'
import { router } from 'kea-router'
import { urls } from 'scenes/urls'
import { ArrowRightOutlined } from '@ant-design/icons'
import { SceneExport } from 'scenes/sceneTypes'
import { sessionRecordingsTableLogic } from 'scenes/session-recordings/sessionRecordingsTableLogic'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { SessionRecordingsPlaylist } from './SessionRecordingsPlaylist'
import { SessionRecordingsFilters } from './SessionRecordingFilters'

export function SessionsRecordings(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    return (
        <div>
            <PageHeader title={<Row align="middle">Recordings</Row>} />
            {currentTeam && !currentTeam?.session_recording_opt_in ? (
                <Alert
                    style={{ marginBottom: 16, display: 'flex', alignItems: 'center' }}
                    message="Recordings are not yet enabled for this project"
                    description="To use this feature, please go to your project settings and enable it."
                    type="info"
                    showIcon
                    action={
                        <Button
                            type="primary"
                            onClick={() => {
                                router.actions.push(urls.projectSettings(), {}, 'recordings')
                            }}
                        >
                            Go to settings <ArrowRightOutlined />
                        </Button>
                    }
                />
            ) : null}
            <SessionRecordingsFilters />
            {featureFlags[FEATURE_FLAGS.SESSION_RECORDINGS_PLAYLIST] ? (
                <SessionRecordingsPlaylist key="global" />
            ) : (
                <SessionRecordingsTable key="global" />
            )}
        </div>
    )
}

export const scene: SceneExport = {
    component: SessionsRecordings,
    logic: sessionRecordingsTableLogic,
}
