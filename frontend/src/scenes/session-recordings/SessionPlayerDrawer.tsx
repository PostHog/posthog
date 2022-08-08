import React from 'react'
import { Drawer } from 'lib/components/Drawer'
import {
    SessionRecordingPlayerV2,
    SessionRecordingPlayerV3,
} from 'scenes/session-recordings/player/SessionRecordingPlayer'
import { Button, Col, Modal, Row } from 'antd'
import { ArrowLeftOutlined } from '@ant-design/icons'
import { IconClose } from 'lib/components/icons'
import { useValues } from 'kea'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { PlayerMetaV3 } from 'scenes/session-recordings/player/PlayerMeta'

interface SessionPlayerDrawerProps {
    isPersonPage?: boolean
    onClose: () => void
}

export function SessionPlayerDrawer({ isPersonPage = false, onClose }: SessionPlayerDrawerProps): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const isSessionRecordingsPlayerV3 = !!featureFlags[FEATURE_FLAGS.SESSION_RECORDINGS_PLAYER_V3]

    if (isSessionRecordingsPlayerV3) {
        return (
            <Modal
                className="session-player-wrapper-v3"
                title={<PlayerMetaV3 />}
                visible
                destroyOnClose
                closeIcon={<IconClose />}
                onCancel={onClose}
                footer={null}
                // zIndex: 1061 ensures it opens above the insight person modal which is 1060
                style={{ zIndex: 1061 }}
            >
                <Col className="session-drawer-body">
                    <SessionRecordingPlayerV3 />
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
            className="session-player-wrapper-v2"
            closable={false}
            // zIndex: 1061 ensures it opens above the insight person modal which is 1060
            style={{ zIndex: 1061 }}
        >
            <Col style={{ height: '100vh', display: 'flex', flexDirection: 'column' }}>
                <Row
                    style={{ height: 48, borderBottom: '1px solid var(--border)', flexShrink: 0 }}
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
                    <SessionRecordingPlayerV2 />
                </Row>
            </Col>
        </Drawer>
    )
}
