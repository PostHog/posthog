import React from 'react'
import { Drawer } from 'lib/components/Drawer'
import { SessionRecordingPlayer } from 'scenes/session-recordings/player/SessionRecordingPlayer'
import { Button, Col, Modal, Row } from 'antd'
import { ArrowLeftOutlined } from '@ant-design/icons'
import { IconClose } from 'lib/components/icons'
import { useValues } from 'kea'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'

interface SessionPlayerDrawerProps {
    isPersonPage?: boolean
    onClose: () => void
}

export function SessionPlayerDrawer({ isPersonPage = false, onClose }: SessionPlayerDrawerProps): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)

    if (featureFlags[FEATURE_FLAGS.SESSION_RECORDINGS_PLAYER_V3]) {
        return (
            <Modal visible>
                <Col style={{ height: '100vh' }}>
                    <Row
                        style={{ height: 48, borderBottom: '1px solid var(--border)' }}
                        align="middle"
                        justify="space-between"
                    >
                        <Button type="link" onClick={onClose}>
                            <ArrowLeftOutlined /> Back to {isPersonPage ? 'persons' : 'recordings'}
                        </Button>
                        <div
                            className="text-muted cursor-pointer flex-center"
                            style={{ fontSize: '1.5em', paddingRight: 8 }}
                            onClick={onClose}
                        >
                            <IconClose />
                        </div>
                    </Row>
                    <Row className="session-drawer-body">
                        <SessionRecordingPlayer />
                    </Row>
                </Col>
            </Modal>
        )
    }

    return (
        <Drawer
            destroyOnClose
            visible
            width="100%"
            onClose={onClose}
            className="session-player-drawer-v2"
            closable={false}
            // zIndex: 1061 ensures it opens above the insight person modal which is 1060
            style={{ zIndex: 1061 }}
        >
            <Col style={{ height: '100vh' }}>
                <Row
                    style={{ height: 48, borderBottom: '1px solid var(--border)' }}
                    align="middle"
                    justify="space-between"
                >
                    <Button type="link" onClick={onClose}>
                        <ArrowLeftOutlined /> Back to {isPersonPage ? 'persons' : 'recordings'}
                    </Button>
                    <div
                        className="text-muted cursor-pointer flex items-center"
                        style={{ fontSize: '1.5em', paddingRight: 8 }}
                        onClick={onClose}
                    >
                        <IconClose />
                    </div>
                </Row>
                <Row className="session-drawer-body">
                    <SessionRecordingPlayer />
                </Row>
            </Col>
        </Drawer>
    )
}
