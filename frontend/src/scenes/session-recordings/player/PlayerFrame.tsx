import React, { MutableRefObject, Ref, useEffect, useRef } from 'react'
import { Handler, viewportResizeDimension } from 'rrweb/typings/types'
import { useActions, useValues } from 'kea'
import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'
import { SessionPlayerState, SessionRecordingPlayerProps } from '~/types'
import { IconPlay } from 'scenes/session-recordings/player/icons'
import useSize from '@react-hook/size'

export const PlayerFrame = React.forwardRef(function PlayerFrameInner(
    { sessionRecordingId, playerKey }: SessionRecordingPlayerProps,
    ref: Ref<HTMLDivElement>
): JSX.Element {
    const replayDimensionRef = useRef<viewportResizeDimension>()
    const { currentPlayerState, player } = useValues(sessionRecordingPlayerLogic({ sessionRecordingId, playerKey }))
    const { togglePlayPause, setScale } = useActions(sessionRecordingPlayerLogic({ sessionRecordingId, playerKey }))
    const frameRef = ref as MutableRefObject<HTMLDivElement>
    const containerRef = useRef<HTMLDivElement | null>(null)
    const containerDimensions = useSize(containerRef)

    // Recalculate the player size when the recording changes dimensions
    useEffect(() => {
        if (!player) {
            return
        }

        player.replayer.on('resize', updatePlayerDimensions as Handler)
        window.addEventListener('resize', windowResize)

        return () => window.removeEventListener('resize', windowResize)
    }, [player?.replayer])

    // Recalculate the player size when the player changes dimensions
    useEffect(() => {
        windowResize()
    }, [containerDimensions])

    const windowResize = (): void => {
        updatePlayerDimensions(replayDimensionRef.current)
    }

    const updatePlayerDimensions = (replayDimensions: viewportResizeDimension | undefined): void => {
        if (!replayDimensions || !frameRef?.current?.parentElement || !player?.replayer) {
            return
        }

        replayDimensionRef.current = replayDimensions

        const parentDimensions = frameRef.current.parentElement.getBoundingClientRect()

        const scale = Math.min(
            parentDimensions.width / replayDimensions.width,
            parentDimensions.height / replayDimensions.height,
            1
        )

        player.replayer.wrapper.style.transform = `scale(${scale})`

        setScale(scale)
    }

    const renderPlayerState = (): JSX.Element | null => {
        if (currentPlayerState === SessionPlayerState.BUFFER) {
            return <div className="rrweb-overlay">Buffering...</div>
        }
        if (currentPlayerState === SessionPlayerState.PAUSE) {
            return (
                <div className="rrweb-overlay">
                    <IconPlay className="rrweb-overlay-play-icon" />
                </div>
            )
        }
        if (currentPlayerState === SessionPlayerState.SKIP) {
            return <div className="rrweb-overlay">Skipping inactivity</div>
        }
        return null
    }

    return (
        <div ref={containerRef} className="rrweb-player" onClick={togglePlayPause}>
            <div className="player-frame" ref={ref} style={{ position: 'absolute' }} />
            <div className="rrweb-overlay-container">{renderPlayerState()}</div>
        </div>
    )
})
