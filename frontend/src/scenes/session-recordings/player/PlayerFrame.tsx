import React, { MutableRefObject, Ref, useEffect, useRef } from 'react'
import { Handler, viewportResizeDimension } from 'rrweb/typings/types'
import { useActions, useValues } from 'kea'
import {
    sessionRecordingPlayerLogic,
    SessionRecordingPlayerLogicProps,
} from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'
import useSize from '@react-hook/size'
import './PlayerFrame.scss'

export const PlayerFrame = React.forwardRef(function PlayerFrameInner(
    { sessionRecordingId, playerKey }: SessionRecordingPlayerLogicProps,
    ref: Ref<HTMLDivElement>
): JSX.Element {
    const replayDimensionRef = useRef<viewportResizeDimension>()
    const { player } = useValues(sessionRecordingPlayerLogic({ sessionRecordingId, playerKey }))
    const { setScale } = useActions(sessionRecordingPlayerLogic({ sessionRecordingId, playerKey }))
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

    return (
        <div ref={containerRef} className="PlayerFrame ph-no-capture">
            <div className="PlayerFrame__content" ref={ref} />
        </div>
    )
})
