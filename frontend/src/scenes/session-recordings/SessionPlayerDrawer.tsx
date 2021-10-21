import React from 'react'

import { Drawer } from 'lib/components/Drawer'
import { SessionsPlay } from 'scenes/sessions/SessionsPlay'
import { SessionRecordingPlayerV2 } from 'scenes/session-recordings/player/SessionRecordingPlayerV2'
import { useValues } from 'kea'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { Button, Col, Row } from 'antd'
import { ArrowLeftOutlined } from '@ant-design/icons'

interface SessionPlayerDrawerProps {
    isPersonPage?: boolean
    onClose: () => void
}

export function SessionPlayerDrawer({ isPersonPage = false, onClose }: SessionPlayerDrawerProps): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)

    return (
        <Drawer
            destroyOnClose
            visible
            width="100%"
            onClose={onClose}
            className={featureFlags[FEATURE_FLAGS.NEW_SESSIONS_PLAYER] ? 'session-player-drawer-v2' : ''}
        >
            {featureFlags[FEATURE_FLAGS.NEW_SESSIONS_PLAYER] ? (
                <Col style={{ height: '100vh' }}>
                    <Row style={{ height: 40 }} align="middle" justify="space-between">
                        <Button type="link" onClick={onClose}>
                            <ArrowLeftOutlined /> Back to{' '}
                            {isPersonPage
                                ? 'persons'
                                : featureFlags[FEATURE_FLAGS.REMOVE_SESSIONS]
                                ? 'recordings'
                                : 'sessions'}
                        </Button>
                    </Row>
                    <Row style={{ height: 'calc(100vh - 40px)' }}>
                        <SessionRecordingPlayerV2 />
                    </Row>
                </Col>
            ) : (
                <>
                    <Button type="link" onClick={onClose}>
                        <ArrowLeftOutlined /> Back to{' '}
                        {isPersonPage
                            ? 'persons'
                            : featureFlags[FEATURE_FLAGS.REMOVE_SESSIONS]
                            ? 'recordings'
                            : 'sessions'}
                    </Button>
                    <SessionsPlay />
                </>
            )}
        </Drawer>
    )
}
