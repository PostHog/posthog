import React, { useEffect, useRef } from 'react'
import { useActions, useValues } from 'kea'
import screenfull from 'screenfull'
import { PLAYBACK_SPEEDS, sessionRecordingPlayerLogic } from './sessionRecordingPlayerLogic'
import { PlayerFrame } from 'scenes/session-recordings/player/PlayerFrame'
import { PlayerController } from 'scenes/session-recordings/player/PlayerController'
import { PlayerEvents } from 'scenes/session-recordings/player/PlayerEvents'
import './styles.scss'

export function SessionRecordingPlayerV2(): JSX.Element {
    const { togglePlayPause, seekForward, seekBackward, setSpeed, initReplayer, stopAnimation } =
        useActions(sessionRecordingPlayerLogic)
    const { snapshots, isPlayable } = useValues(sessionRecordingPlayerLogic)
    const frame = useRef<HTMLDivElement | null>(null)

    console.log('RECORDING', snapshots.length)

    // Need useEffect to populate replayer on component paint
    useEffect(() => {
        if (frame.current && isPlayable) {
            stopAnimation()
            initReplayer(frame)

            return () => stopAnimation()
        }
    }, [frame, isPlayable])

    const toggleFullScreen = (): void => {
        if (screenfull.isEnabled && frame.current) {
            screenfull.toggle(frame.current)
        }
    }

    const handleKeyDown = (event: React.KeyboardEvent<HTMLDivElement>): void => {
        if (event.key === ' ') {
            togglePlayPause()
            event.preventDefault()
        } else if (event.key === 'ArrowLeft') {
            seekBackward()
        } else if (event.key === 'ArrowRight') {
            seekForward()
        } else if (event.key === 'f') {
            toggleFullScreen()
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
        <div
            className="session-player v2"
            onKeyDown={handleKeyDown}
            tabIndex={0}
            style={{ height: '100%', width: '100%' }}
        >
            <PlayerFrame ref={frame} />
            <PlayerController toggleFullScreen={toggleFullScreen} />
            <PlayerEvents />
        </div>
    )
}
