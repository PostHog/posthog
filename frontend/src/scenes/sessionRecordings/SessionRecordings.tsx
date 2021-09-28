import React from 'react'
import { SessionRecordingsTable } from './SessionRecordingsTable'
import { PageHeader } from 'lib/components/PageHeader'
import { Alert, Button, Row, Tag } from 'antd'
import { teamLogic } from 'scenes/teamLogic'
import { useValues } from 'kea'
import { router } from 'kea-router'
import { urls } from 'scenes/sceneLogic'

export function SessionsRecordings(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    return (
        <div>
            <Row style={{ alignItems: 'center', marginBottom: 16 }}>
                <PageHeader title="Session Recordings" />
                <Tag color="orange" style={{ marginLeft: 8, marginTop: 16 }}>
                    BETA
                </Tag>
            </Row>
            {currentTeam && !currentTeam?.session_recording_opt_in ? (
                <Alert
                    style={{ marginBottom: 16 }}
                    message="Session recordings are not enabled for this project"
                    description="To use this feature, please go to your project settings and enable it."
                    type="info"
                    showIcon
                    action={
                        <Button
                            size="large"
                            type="primary"
                            onClick={() => {
                                router.actions.push(urls.projectSettings(), {}, 'session-recording')
                            }}
                        >
                            Project settings
                        </Button>
                    }
                />
            ) : null}

            <SessionRecordingsTable key="global" />
        </div>
    )
}
