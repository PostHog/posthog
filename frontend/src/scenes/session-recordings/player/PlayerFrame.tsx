import './PlayerFrame.scss'

import { Handler, viewportResizeDimension } from '@posthog/rrweb-types'
import useSize from '@react-hook/size'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { useCallback, useEffect, useRef } from 'react'
import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'

export const PlayerFrame = (): JSX.Element => {
    const replayDimensionRef = useRef<viewportResizeDimension>()
    const { player, sessionRecordingId, maskingWindow } = useValues(sessionRecordingPlayerLogic)
    const { setScale, setRootFrame } = useActions(sessionRecordingPlayerLogic)

    const frameRef = useRef<HTMLDivElement | null>(null)
    const containerRef = useRef<HTMLDivElement | null>(null)
    const containerDimensions = useSize(containerRef)

    // Define callbacks before they're used in effects
    const updatePlayerDimensions = useCallback(
        (replayDimensions: viewportResizeDimension | undefined): void => {
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

            // Check if player still exists before updating (defensive check)
            if (player?.replayer?.wrapper) {
                player.replayer.wrapper.style.transform = `scale(${scale})`
            }

            setScale(scale)
        },
        [player, setScale]
    )

    const windowResize = useCallback((): void => {
        updatePlayerDimensions(replayDimensionRef.current)
    }, [updatePlayerDimensions])

    // Need useEffect to populate replayer on component paint
    useEffect(() => {
        if (frameRef.current) {
            setRootFrame(frameRef.current)
        }
    }, [frameRef, sessionRecordingId, setRootFrame])

    // Cleanup ref on unmount
    useEffect(() => {
        return () => {
            replayDimensionRef.current = undefined
        }
    }, [])

    // Recalculate the player size when the recording changes dimensions
    useEffect(() => {
        if (!player) {
            return
        }

        player.replayer.on('resize', updatePlayerDimensions as Handler)
        window.addEventListener('resize', windowResize)

        return () => {
            player.replayer.off('resize', updatePlayerDimensions as Handler)
            window.removeEventListener('resize', windowResize)
        }
    }, [player, updatePlayerDimensions, windowResize])

    // Recalculate the player size when the player changes dimensions
    useEffect(() => {
        windowResize()
    }, [containerDimensions, windowResize])

    return (
        <div ref={containerRef} className="PlayerFrame ph-no-capture">
            <div
                className={clsx('PlayerFrame__content', maskingWindow && 'PlayerFrame__content--masking-window')}
                ref={frameRef}
            />
        </div>
    )
}
