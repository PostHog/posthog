import './styles.scss'
import React, { useEffect, useRef } from 'react'
import { useActions, useValues } from 'kea'
import { sessionRecordingPlayerLogic } from './sessionRecordingPlayerLogic'
import { PlayerFrame } from 'scenes/session-recordings/player/PlayerFrame'
import { PlayerControllerV2, PlayerControllerV3 } from 'scenes/session-recordings/player/PlayerController'
import { Col, Row } from 'antd'
import { LemonDivider } from 'lib/components/LemonDivider'
import { PlayerInspectorV2, PlayerInspectorV3 } from 'scenes/session-recordings/player/PlayerInspector'
import { PlayerFilter } from 'scenes/session-recordings/player/list/PlayerFilter'
import { SessionRecordingPlayerProps } from '~/types'
import { PlayerMetaV3 } from './PlayerMeta'

export function useFrameRef({
    sessionRecordingId,
    playerKey,
}: SessionRecordingPlayerProps): React.MutableRefObject<HTMLDivElement | null> {
    const { setRootFrame } = useActions(sessionRecordingPlayerLogic({ sessionRecordingId, playerKey }))
    const frame = useRef<HTMLDivElement | null>(null)
    // Need useEffect to populate replayer on component paint
    useEffect(() => {
        if (frame.current) {
            setRootFrame(frame.current)
        }
    }, [frame, sessionRecordingId])

    return frame
}

export function SessionRecordingPlayerV2({ sessionRecordingId, playerKey }: SessionRecordingPlayerProps): JSX.Element {
    const { handleKeyDown } = useActions(sessionRecordingPlayerLogic({ sessionRecordingId, playerKey }))
    const { isSmallScreen } = useValues(sessionRecordingPlayerLogic({ sessionRecordingId, playerKey }))
    const frame = useFrameRef({ sessionRecordingId, playerKey })
    return (
        <Col className="session-player-v2" onKeyDown={handleKeyDown} tabIndex={0} flex={1}>
            <Row className="session-player-body" wrap={false}>
                <div className="player-container ph-no-capture">
                    <PlayerFrame ref={frame} sessionRecordingId={sessionRecordingId} playerKey={playerKey} />
                </div>
                {!isSmallScreen && <PlayerInspectorV2 sessionRecordingId={sessionRecordingId} playerKey={playerKey} />}
            </Row>
            <Row className="player-controller" align="middle">
                <PlayerControllerV2 sessionRecordingId={sessionRecordingId} playerKey={playerKey} />
            </Row>
            {isSmallScreen && <PlayerInspectorV2 sessionRecordingId={sessionRecordingId} playerKey={playerKey} />}
        </Col>
    )
}

export function SessionRecordingPlayerV3({
    sessionRecordingId,
    playerKey,
    includeMeta = true,
    recordingStartTime, // While optional, including recordingStartTime allows the underlying ClickHouse query to be much faster
}: SessionRecordingPlayerProps): JSX.Element {
    const { handleKeyDown } = useActions(
        sessionRecordingPlayerLogic({ sessionRecordingId, playerKey, recordingStartTime })
    )
    const frame = useFrameRef({ sessionRecordingId, playerKey })
    return (
        <Col className="session-player-v3" onKeyDown={handleKeyDown} tabIndex={0} flex={1}>
            {includeMeta ? <PlayerMetaV3 sessionRecordingId={sessionRecordingId} playerKey={playerKey} /> : null}
            <div className="session-player-body flex">
                <div className="player-container ph-no-capture">
                    <PlayerFrame sessionRecordingId={sessionRecordingId} ref={frame} playerKey={playerKey} />
                </div>
            </div>
            <LemonDivider className="my-0" />
            <div className="player-controller items-center flex">
                <PlayerControllerV3 sessionRecordingId={sessionRecordingId} playerKey={playerKey} />
            </div>
            <LemonDivider className="my-0" />
            <Row className="player-filter" align="middle">
                <PlayerFilter sessionRecordingId={sessionRecordingId} playerKey={playerKey} />
            </Row>
            <LemonDivider className="my-0" />
            <PlayerInspectorV3 sessionRecordingId={sessionRecordingId} playerKey={playerKey} />
        </Col>
    )
}
