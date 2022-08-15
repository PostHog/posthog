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

export function SessionsRecordings(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
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

            <SessionRecordingsTable key="global" />
        </div>
    )
}

export const scene: SceneExport = {
    component: SessionsRecordings,
    logic: sessionRecordingsTableLogic,
}
