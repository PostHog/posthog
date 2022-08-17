import './styles.scss'
import React, { useEffect, useRef } from 'react'
import { useActions, useValues } from 'kea'
import { sessionRecordingPlayerLogic } from './sessionRecordingPlayerLogic'
import { PlayerFrame } from 'scenes/session-recordings/player/PlayerFrame'
import { PlayerControllerV2, PlayerControllerV3 } from 'scenes/session-recordings/player/PlayerController'
import { Col, Row } from 'antd'
import { LemonDivider } from 'lib/components/LemonDivider'
import { PlayerInspectorV2, PlayerInspectorV3 } from 'scenes/session-recordings/player/PlayerInspector'
import { PlayerMetaV3 } from './PlayerMeta'
import { SessionRecordingProps } from '~/types'

export function useFrameRef({
    sessionRecordingId,
}: SessionRecordingProps): React.MutableRefObject<HTMLDivElement | null> {
    const { setRootFrame } = useActions(sessionRecordingPlayerLogic({ sessionRecordingId }))
    const frame = useRef<HTMLDivElement | null>(null)
    // Need useEffect to populate replayer on component paint
    useEffect(() => {
        if (frame.current) {
            setRootFrame(frame.current)
        }
    }, [frame, sessionRecordingId])

    return frame
}

export function SessionRecordingPlayerV2({ sessionRecordingId }: SessionRecordingProps): JSX.Element {
    const { handleKeyDown } = useActions(sessionRecordingPlayerLogic({ sessionRecordingId }))
    const { isSmallScreen } = useValues(sessionRecordingPlayerLogic({ sessionRecordingId }))
    const frame = useFrameRef({ sessionRecordingId })
    return (
        <Col className="session-player-v2" onKeyDown={handleKeyDown} tabIndex={0} flex={1}>
            <Row className="session-player-body" wrap={false}>
                <div className="player-container ph-no-capture">
                    <PlayerFrame ref={frame} sessionRecordingId={sessionRecordingId} />
                </div>
                {!isSmallScreen && <PlayerInspectorV2 sessionRecordingId={sessionRecordingId} />}
            </Row>
            <Row className="player-controller" align="middle">
                <PlayerControllerV2 sessionRecordingId={sessionRecordingId} />
            </Row>
            {isSmallScreen && <PlayerInspectorV2 sessionRecordingId={sessionRecordingId} />}
        </Col>
    )
}

export function SessionRecordingPlayerV3({ sessionRecordingId }: SessionRecordingProps): JSX.Element {
    const { handleKeyDown } = useActions(sessionRecordingPlayerLogic({ sessionRecordingId }))
    const frame = useFrameRef({ sessionRecordingId })
    return (
        <Col className="session-player-v3" onKeyDown={handleKeyDown} tabIndex={0} flex={1}>
            <PlayerMetaV3 sessionRecordingId={sessionRecordingId} />
            <div className="session-player-body flex">
                <div className="player-container ph-no-capture">
                    <PlayerFrame sessionRecordingId={sessionRecordingId} ref={frame} />
                </div>
            </div>
            <LemonDivider className="my-0" />
            <div className="player-controller items-center flex">
                <PlayerControllerV3 sessionRecordingId={sessionRecordingId} />
            </div>
            <LemonDivider className="my-0" />
            <PlayerInspectorV3 sessionRecordingId={sessionRecordingId} />
        </Col>
    )
}
