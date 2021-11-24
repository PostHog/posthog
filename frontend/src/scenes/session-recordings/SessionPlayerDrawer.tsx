import React from 'react'
import { Drawer } from 'lib/components/Drawer'
import { SessionRecordingPlayerV2 } from 'scenes/session-recordings/player/SessionRecordingPlayerV2'
import { Button, Col, Row } from 'antd'
import { ArrowLeftOutlined } from '@ant-design/icons'

interface SessionPlayerDrawerProps {
    isPersonPage?: boolean
    onClose: () => void
}

export function SessionPlayerDrawer({ isPersonPage = false, onClose }: SessionPlayerDrawerProps): JSX.Element {
    return (
        <Drawer destroyOnClose visible width="100%" onClose={onClose} className="session-player-drawer-v2">
            <Col style={{ height: '100vh' }}>
                <Row
                    style={{ height: 48, borderBottom: '1px solid var(--border)' }}
                    align="middle"
                    justify="space-between"
                >
                    <Button type="link" onClick={onClose}>
                        <ArrowLeftOutlined /> Back to {isPersonPage ? 'persons' : 'recordings'}
                    </Button>
                </Row>
                <Row className="session-drawer-body">
                    <SessionRecordingPlayerV2 />
                </Row>
            </Col>
        </Drawer>
    )
}
