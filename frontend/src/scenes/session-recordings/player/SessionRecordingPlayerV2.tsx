import './styles.scss'
import React, { useEffect, useRef } from 'react'
import { useActions, useValues } from 'kea'
import { PLAYBACK_SPEEDS, sessionRecordingPlayerLogic } from './sessionRecordingPlayerLogic'
import { PlayerFrame } from 'scenes/session-recordings/player/PlayerFrame'
import { PlayerController } from 'scenes/session-recordings/player/PlayerController'
import { PlayerEvents } from 'scenes/session-recordings/player/PlayerEvents'
import { Col, Row } from 'antd'

export function SessionRecordingPlayerV2(): JSX.Element {
    const { togglePlayPause, seekForward, seekBackward, setSpeed, initReplayer, stopAnimation } =
        useActions(sessionRecordingPlayerLogic)
    const { isPlayable } = useValues(sessionRecordingPlayerLogic)
    const frame = useRef<HTMLDivElement | null>(null)

    // Need useEffect to populate replayer on component paint
    useEffect(() => {
        if (frame.current && isPlayable) {
            stopAnimation()
            initReplayer(frame)

            return () => stopAnimation()
        }
    }, [frame, isPlayable])

    const handleKeyDown = (event: React.KeyboardEvent<HTMLDivElement>): void => {
        if (event.key === ' ') {
            togglePlayPause()
            event.preventDefault()
        } else if (event.key === 'ArrowLeft') {
            seekBackward()
        } else if (event.key === 'ArrowRight') {
            seekForward()
        } else {
            // Playback speeds shortcuts
            for (let i = 0; i < PLAYBACK_SPEEDS.length; i++) {
                if (event.key === (i + 1).toString()) {
                    setSpeed(PLAYBACK_SPEEDS[i])
                }
            }
        }
    }

    return (
        <Col className="session-player-v2" onKeyDown={handleKeyDown} tabIndex={0} flex={1}>
            <Row className="session-player-body" wrap={false}>
                <Col className="player-container ph-no-capture" span={16}>
                    <PlayerFrame ref={frame} />
                </Col>
                <Col className="player-events" span={8}>
                    <PlayerEvents />
                </Col>
            </Row>
            <Row className="session-player-controller" align="middle">
                <PlayerController />
            </Row>
        </Col>
    )
}
