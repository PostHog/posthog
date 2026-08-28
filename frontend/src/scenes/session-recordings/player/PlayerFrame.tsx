import './PlayerFrame.scss'
import './PlayerFrameLLMHighlight.scss'

import useSize from '@react-hook/size'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { Handler, viewportResizeDimension } from 'posthog-js/rrweb-types'
import { useCallback, useEffect, useRef } from 'react'

import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'

const BASE_CLICK_INDICATOR_DURATION_S = 1 / 3

export const PlayerFrame = (): JSX.Element => {
    const replayDimensionRef = useRef<viewportResizeDimension>()
    const { player, sessionRecordingId, maskingWindow, speed, resolution } = useValues(sessionRecordingPlayerLogic)
    const { setScale, setRootFrame } = useActions(sessionRecordingPlayerLogic)

    const frameRef = useRef<HTMLDivElement | null>(null)
    const containerRef = useRef<HTMLDivElement | null>(null)
    const containerDimensions = useSize(containerRef)

    // Define callbacks before they're used in effects
    const updatePlayerDimensions = useCallback(
        (replayDimensions: viewportResizeDimension | undefined): void => {
            // The rrweb replayer only reports dimensions through its `resize` event, which
            // never fires for a recording whose first full snapshot arrived late. Fall back
            // to the recording's known resolution so the frame still scales to its container.
            const dimensions = replayDimensions ?? resolution ?? undefined

            if (!dimensions || !frameRef?.current?.parentElement || !player?.replayer || !player?.replayer.wrapper) {
                return
            }

            replayDimensionRef.current = dimensions

            const parentDimensions = frameRef.current.parentElement.getBoundingClientRect()

            const scale = Math.min(
                parentDimensions.width / dimensions.width,
                parentDimensions.height / dimensions.height,
                1
            )

            // Scale with `zoom` instead of `transform: scale()`. A decimal transform scale
            // promotes the large replay iframe to a composited layer, which WebKit
            // re-rasterizes at pinch-zoom scale and crashes the tab on iOS (FB13816677).
            // `zoom` scales through layout, so no oversized layer exists. This also avoids
            // the Chrome GPU bug where an identity transform painted the iframe layer
            // outside its clipping bounds, which previously forced a 0.999 scale cap.
            player.replayer.wrapper.style.setProperty('zoom', String(scale))

            setScale(scale)
        },
        [player, setScale, resolution]
    )

    const windowResize = useCallback((): void => {
        updatePlayerDimensions(replayDimensionRef.current)
    }, [updatePlayerDimensions])

    // Need useEffect to populate replayer on component paint
    useEffect(() => {
        if (frameRef.current) {
            setRootFrame(frameRef.current)
        }
    }, [sessionRecordingId, setRootFrame])

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
        // Adding the LLM highlight class to override clicks animation, in case we decide to make it conditional.
        // The initial approach was conditional, but everyone liked how it looked, so we decided to make it the default.
        // Click indicator duration scales with playback speed: 1/3s at 1x, 1/6s at 2x, etc.
        <div
            ref={containerRef}
            className={clsx('PlayerFrame ph-no-capture PlayerFrame--llm-highlight')}
            style={
                {
                    '--player-frame-click-duration': `${BASE_CLICK_INDICATOR_DURATION_S / speed}s`,
                } as React.CSSProperties
            }
        >
            <div
                className={clsx('PlayerFrame__content', maskingWindow && 'PlayerFrame__content--masking-window')}
                ref={frameRef}
            />
        </div>
    )
}
