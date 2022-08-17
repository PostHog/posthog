import React, { MutableRefObject, Ref, useEffect, useRef } from 'react'
import { Handler, viewportResizeDimension } from 'rrweb/typings/types'
import { useActions, useValues } from 'kea'
import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'
import { SessionPlayerState, SessionRecordingProps } from '~/types'
import { IconPlay } from 'scenes/session-recordings/player/icons'

interface PlayerFrameProps extends SessionRecordingProps {
    height?: number
    width?: number
}

export const PlayerFrame = React.forwardRef(function PlayerFrameInner(
    { height, width, sessionRecordingId }: PlayerFrameProps,
    ref: Ref<HTMLDivElement>
): JSX.Element {
    const replayDimensionRef = useRef<viewportResizeDimension>()
    const { currentPlayerState, player } = useValues(sessionRecordingPlayerLogic({ sessionRecordingId }))
    const { togglePlayPause, setScale } = useActions(sessionRecordingPlayerLogic({ sessionRecordingId }))
    const frameRef = ref as MutableRefObject<HTMLDivElement>

    useEffect(() => {
        if (!player) {
            return
        }

        player.replayer.on('resize', updatePlayerDimensions as Handler)
        window.addEventListener('resize', windowResize)

        return () => window.removeEventListener('resize', windowResize)
    }, [player?.replayer])

    const windowResize = (): void => {
        updatePlayerDimensions(replayDimensionRef.current)
    }

    useEffect(() => {
        updatePlayerDimensions(replayDimensionRef.current)
    }, [height, width])

    // :TRICKY: Scale down the iframe and try to position it vertically
    const updatePlayerDimensions = (replayDimensions: viewportResizeDimension | undefined): void => {
        if (!replayDimensions || !frameRef?.current?.parentElement || !player?.replayer) {
            return
        }

        replayDimensionRef.current = replayDimensions

        const parentDimensions = frameRef.current.parentElement.getBoundingClientRect()
        const widthToUse = width || parentDimensions.width
        const heightToUse = height || parentDimensions.height

        const scale = Math.min(widthToUse / replayDimensions.width, heightToUse / replayDimensions.height, 1)

        player.replayer.wrapper.style.transform = `scale(${scale})`
        frameRef.current.style.paddingLeft = `${(widthToUse - replayDimensions.width * scale) / 2}px`
        frameRef.current.style.paddingTop = `${(heightToUse - replayDimensions.height * scale) / 2}px`
        frameRef.current.style.marginBottom = `-${heightToUse - replayDimensions.height * scale}px`
        frameRef.current.style.height = `${heightToUse}px`
        frameRef.current.style.width = `${widthToUse}px`
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
        <div className="rrweb-player" onClick={togglePlayPause}>
            <div ref={ref} />
            <div className="rrweb-overlay-container">{renderPlayerState()}</div>
        </div>
    )
})
