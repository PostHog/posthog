import './PlayerFrame.scss'
import './PlayerFrameLLMHighlight.scss'

import useSize from '@react-hook/size'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { useEffect, useRef } from 'react'

import { Handler, viewportResizeDimension } from '@posthog/rrweb-types'

import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'

export const PlayerFrame = (): JSX.Element => {
    const replayDimensionRef = useRef<viewportResizeDimension>()
    const { player, sessionRecordingId, maskingWindow } = useValues(sessionRecordingPlayerLogic)
    const { setScale, setRootFrame } = useActions(sessionRecordingPlayerLogic)

    const frameRef = useRef<HTMLDivElement | null>(null)
    const containerRef = useRef<HTMLDivElement | null>(null)
    const containerDimensions = useSize(containerRef)

    const playerRef = useRef(player)
    playerRef.current = player

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

        const updatePlayerDimensions = (replayDimensions: viewportResizeDimension | undefined): void => {
            const currentPlayer = playerRef.current
            if (
                !replayDimensions ||
                !frameRef?.current?.parentElement ||
                !currentPlayer?.replayer ||
                !currentPlayer?.replayer.wrapper
            ) {
                return
            }

            replayDimensionRef.current = replayDimensions

            const parentDimensions = frameRef.current.parentElement.getBoundingClientRect()

            const scale = Math.min(
                parentDimensions.width / replayDimensions.width,
                parentDimensions.height / replayDimensions.height,
                1
            )

            currentPlayer.replayer.wrapper.style.transform = `scale(${scale})`

            setScale(scale)
        }

        const windowResize = (): void => {
            updatePlayerDimensions(replayDimensionRef.current)
        }

        player.replayer.on('resize', updatePlayerDimensions as Handler)
        window.addEventListener('resize', windowResize)

        return () => {
            window.removeEventListener('resize', windowResize)
            try {
                player.replayer.off('resize', updatePlayerDimensions as Handler)
            } catch {
                // Replayer may already be destroyed
            }
        }
    }, [player, setScale])

    // Recalculate the player size when the player changes dimensions
    useEffect(() => {
        if (!player?.replayer?.wrapper) {
            return
        }

        const replayDimensions = replayDimensionRef.current
        if (!replayDimensions || !frameRef?.current?.parentElement) {
            return
        }

        const parentDimensions = frameRef.current.parentElement.getBoundingClientRect()
        const scale = Math.min(
            parentDimensions.width / replayDimensions.width,
            parentDimensions.height / replayDimensions.height,
            1
        )

        player.replayer.wrapper.style.transform = `scale(${scale})`
        setScale(scale)
    }, [containerDimensions, player, setScale])

    return (
        // Adding the LLM highlight class to override clicks animation, in case we decide to make it conditional.
        // The initial approach was conditional, but everyone liked how it looked, so we decided to make it the default.
        <div ref={containerRef} className={clsx('PlayerFrame ph-no-capture PlayerFrame--llm-highlight')}>
            <div
                className={clsx('PlayerFrame__content', maskingWindow && 'PlayerFrame__content--masking-window')}
                ref={frameRef}
            />
        </div>
    )
}
