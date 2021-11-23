import './styles.scss'
import React, { useEffect, useRef } from 'react'
import { useActions, useValues } from 'kea'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { PLAYBACK_SPEEDS, sessionRecordingPlayerLogic } from './sessionRecordingPlayerLogic'
import { PlayerFrame } from 'scenes/session-recordings/player/PlayerFrame'
import { PlayerController } from 'scenes/session-recordings/player/PlayerController'
import { PlayerEvents } from 'scenes/session-recordings/player/PlayerEvents'
import { Col, Row } from 'antd'
import { FEATURE_FLAGS } from 'lib/constants'
import { PlayerMeta } from 'scenes/session-recordings/player/PlayerMeta'

export function SessionRecordingPlayerV2(): JSX.Element {
    const { togglePlayPause, seekForward, seekBackward, setSpeed, initReplayer, stopAnimation } =
        useActions(sessionRecordingPlayerLogic)
    const { isPlayable, isSmallScreen } = useValues(sessionRecordingPlayerLogic)
    const { featureFlags } = useValues(featureFlagLogic)
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
        // Don't trigger keydown evens if in input box
        if ((event.target as HTMLInputElement)?.matches('input')) {
            return
        }
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
                <div className="player-container ph-no-capture">
                    <PlayerFrame ref={frame} />
                </div>
                {featureFlags[FEATURE_FLAGS.NEW_SESSIONS_PLAYER_EVENTS_LIST] && !isSmallScreen && <PlayerSidebar />}
            </Row>
            <Row className="player-controller" align="middle">
                <PlayerController />
            </Row>
            {featureFlags[FEATURE_FLAGS.NEW_SESSIONS_PLAYER_EVENTS_LIST] && isSmallScreen && <PlayerSidebar />}
        </Col>
    )
}

function PlayerSidebar(): JSX.Element {
    return (
        <Col className="player-sidebar">
            <div className="player-meta">
                <PlayerMeta />
            </div>
            <div className="player-events">
                <PlayerEvents />
            </div>
        </Col>
    )
}
