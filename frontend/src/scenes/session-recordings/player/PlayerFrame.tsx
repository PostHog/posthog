import './PlayerFrame.scss'

import useSize from '@react-hook/size'
import { Handler, viewportResizeDimension } from '@rrweb/types'
import { useActions, useValues } from 'kea'
import { useEffect, useRef } from 'react'
import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'

export const PlayerFrame = (): JSX.Element => {
    const replayDimensionRef = useRef<viewportResizeDimension>()
    const { player, sessionRecordingId } = useValues(sessionRecordingPlayerLogic)
    const { setScale, setRootFrame, playerErrorSeen } = useActions(sessionRecordingPlayerLogic)

    const frameRef = useRef<HTMLDivElement | null>(null)
    // Need useEffect to populate replayer on component paint
    useEffect(() => {
        if (frameRef.current) {
            setRootFrame(frameRef.current)
        }
    }, [frameRef, sessionRecordingId])

    const containerRef = useRef<HTMLDivElement | null>(null)
    const containerDimensions = useSize(containerRef)

    // Recalculate the player size when the recording changes dimensions
    useEffect(() => {
        if (!player) {
            return
        }

        const handleReplayerErrors = (event: ErrorEvent): void => {
            // sometimes replayer throws errors but playback can continue
            // we don't want to show an error message in that case
            // so let's swallow but report replayer errors
            if (event.error && event.error.stack?.includes('Replayer.')) {
                event.preventDefault()
                event.stopPropagation()
                playerErrorSeen(event)
            }
        }

        player.replayer.on('resize', updatePlayerDimensions as Handler)
        window.addEventListener('resize', windowResize)
        window.addEventListener('error', handleReplayerErrors)

        return () => {
            window.removeEventListener('resize', windowResize)
            window.removeEventListener('error', handleReplayerErrors)
        }
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

    return (
        <div ref={containerRef} className="PlayerFrame ph-no-capture">
            <div className="PlayerFrame__content" ref={frameRef} />
        </div>
    )
}
