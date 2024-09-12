import './PlayerFrame.scss'

import useSize from '@react-hook/size'
import { Handler, viewportResizeDimension } from '@rrweb/types'
import { useActions, useValues } from 'kea'
import { useEffect, useRef } from 'react'
import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'

export const PlayerFrame = (): JSX.Element => {
    const replayDimensionRef = useRef<viewportResizeDimension>()
    const { player, sessionRecordingId } = useValues(sessionRecordingPlayerLogic)
    const { setRootFrame } = useActions(sessionRecordingPlayerLogic)

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

        player.replayer.on('resize', updatePlayerDimensions as Handler)
        window.addEventListener('resize', windowResize)

        return () => {
            window.removeEventListener('resize', windowResize)
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
    }

    return (
        <div ref={containerRef} className="PlayerFrame ph-no-capture">
            <div className="PlayerFrame__content" ref={frameRef} />
        </div>
    )
}
