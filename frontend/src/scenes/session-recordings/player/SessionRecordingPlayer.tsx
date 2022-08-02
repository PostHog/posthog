import './styles.scss'
import React, { useEffect, useRef } from 'react'
import { useActions, useValues } from 'kea'
import { sessionRecordingPlayerLogic } from './sessionRecordingPlayerLogic'
import { PlayerFrame } from 'scenes/session-recordings/player/PlayerFrame'
import { PlayerControllerV2, PlayerControllerV3 } from 'scenes/session-recordings/player/PlayerController'
import { Col, Row } from 'antd'
import { LemonDivider } from 'lib/components/LemonDivider'
import { PlayerSidebarV2, PlayerSidebarV3 } from 'scenes/session-recordings/player/PlayerSidebar'

export function useFrameRef(): React.MutableRefObject<HTMLDivElement | null> {
    const { setRootFrame } = useActions(sessionRecordingPlayerLogic)
    const frame = useRef<HTMLDivElement | null>(null)
    // Need useEffect to populate replayer on component paint
    useEffect(() => {
        if (frame.current) {
            setRootFrame(frame.current)
        }
    }, [frame])

    return frame
}

export function SessionRecordingPlayerV2(): JSX.Element {
    const { handleKeyDown } = useActions(sessionRecordingPlayerLogic)
    const { isSmallScreen } = useValues(sessionRecordingPlayerLogic)
    const frame = useFrameRef()
    return (
        <Col className="session-player-v2" onKeyDown={handleKeyDown} tabIndex={0} flex={1}>
            <Row className="session-player-body" wrap={false}>
                <div className="player-container ph-no-capture">
                    <PlayerFrame ref={frame} />
                </div>
                {!isSmallScreen && <PlayerSidebarV2 />}
            </Row>
            <Row className="player-controller" align="middle">
                <PlayerControllerV2 />
            </Row>
            {isSmallScreen && <PlayerSidebarV2 />}
        </Col>
    )
}

export function SessionRecordingPlayerV3(): JSX.Element {
    const { handleKeyDown } = useActions(sessionRecordingPlayerLogic)
    const frame = useFrameRef()
    return (
        <Col className="session-player-v3" onKeyDown={handleKeyDown} tabIndex={0} flex={1}>
            <Row className="session-player-body" wrap={false}>
                <div className="player-container ph-no-capture">
                    <PlayerFrame ref={frame} />
                </div>
            </Row>
            <LemonDivider style={{ margin: 0 }} />
            <Row className="player-controller" align="middle">
                <PlayerControllerV3 />
            </Row>
            <LemonDivider style={{ margin: 0 }} />
            <PlayerSidebarV3 />
        </Col>
    )
}
