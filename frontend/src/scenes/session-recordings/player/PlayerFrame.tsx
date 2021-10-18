import React, { MutableRefObject, useEffect, useRef } from 'react'
import { Handler, viewportResizeDimension } from 'rrweb/typings/types'
import { useActions, useValues } from 'kea'
import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'
import { SessionPlayerState } from '~/types'

export const PlayerFrame = React.forwardRef<HTMLDivElement>(function PlayerFrameInner(_, ref): JSX.Element {
    const replayDimensionRef = useRef<viewportResizeDimension>()
    const { currentPlayerState, replayer } = useValues(sessionRecordingPlayerLogic)
    const { togglePlayPause } = useActions(sessionRecordingPlayerLogic)
    const frameRef = ref as MutableRefObject<HTMLDivElement>

    useEffect(() => {
        if (!replayer) {
            return
        }

        replayer.on('resize', updatePlayerDimensions as Handler)
        window.addEventListener('resize', windowResize)

        return () => window.removeEventListener('resize', windowResize)
    }, [replayer])

    const windowResize = (): void => {
        updatePlayerDimensions(replayDimensionRef.current)
    }

    // :TRICKY: Scale down the iframe and try to position it vertically
    const updatePlayerDimensions = (replayDimensions: viewportResizeDimension | undefined): void => {
        if (!replayDimensions || !frameRef?.current?.parentElement || !replayer) {
            return
        }

        replayDimensionRef.current = replayDimensions
        const { width, height } = frameRef.current.parentElement.getBoundingClientRect()

        const scale = Math.min(width / replayDimensions.width, height / replayDimensions.height, 1)

        replayer.wrapper.style.transform = `scale(${scale})`
        frameRef.current.style.paddingLeft = `${(width - replayDimensions.width * scale) / 2}px`
        frameRef.current.style.paddingTop = `${(height - replayDimensions.height * scale) / 2}px`
        frameRef.current.style.marginBottom = `-${height - replayDimensions.height * scale}px`
    }

    return (
        <div className="rrweb-player" onClick={togglePlayPause}>
            <div ref={ref} />
            <div className="rrweb-overlay-container">
                {currentPlayerState === SessionPlayerState.SKIP && (
                    <div className="rrweb-overlay">Skipping inactivity...</div>
                )}
                {currentPlayerState === SessionPlayerState.BUFFER && <div className="rrweb-overlay">Buffering</div>}
                {currentPlayerState === SessionPlayerState.PAUSE && <div className="rrweb-overlay">Pause</div>}
            </div>
        </div>
    )
})
