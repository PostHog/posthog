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
    const { player, sessionRecordingId, maskingWindow, speed } = useValues(sessionRecordingPlayerLogic)
    const { setScale, setRootFrame } = useActions(sessionRecordingPlayerLogic)

    const frameRef = useRef<HTMLDivElement | null>(null)
    const containerRef = useRef<HTMLDivElement | null>(null)
    const containerDimensions = useSize(containerRef)
    // Tracks the wrapper we last scaled and the scale we applied. Keying on the wrapper node lets
    // us skip redundant updates without stranding a freshly re-initialized wrapper (a re-inited
    // replayer gets a brand-new wrapper that still needs its transform).
    const lastAppliedRef = useRef<{ wrapper: HTMLElement; scale: number } | null>(null)

    // Define callbacks before they're used in effects
    const updatePlayerDimensions = useCallback(
        (replayDimensions: viewportResizeDimension | undefined): void => {
            if (
                !replayDimensions ||
                !frameRef?.current?.parentElement ||
                !player?.replayer ||
                !player?.replayer.wrapper
            ) {
                return
            }

            replayDimensionRef.current = replayDimensions

            const parentDimensions = frameRef.current.parentElement.getBoundingClientRect()

            // Cap at 0.999 instead of 1 to avoid a Chrome GPU compositing bug where
            // an identity transform (scale(1)) causes the iframe layer to paint outside
            // its clipping bounds, overlapping the rest of the UI.
            const scale = Math.min(
                parentDimensions.width / replayDimensions.width,
                parentDimensions.height / replayDimensions.height,
                0.999
            )

            const wrapper = player.replayer.wrapper
            // Skip sub-percent updates on the same wrapper. A layout feedback loop (e.g. a
            // scrollbar toggling, or the scale readout itself reflowing) makes the fit-scale
            // oscillate between two values a fraction of a percent apart; without this the
            // transform re-applies and setScale re-dispatches every frame, visibly shaking the
            // player and churning every playerMetaLogic consumer. 0.005 pins the value once it
            // settles while staying finer than any resize a viewer would notice. A re-initialized
            // replayer has a fresh wrapper, so it still gets its transform even when scale is unchanged.
            if (lastAppliedRef.current?.wrapper === wrapper && Math.abs(lastAppliedRef.current.scale - scale) < 0.005) {
                return
            }
            lastAppliedRef.current = { wrapper, scale }

            wrapper.style.transform = `scale(${scale})`

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
