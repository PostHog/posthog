import React, { MutableRefObject, Ref, useEffect, useRef } from 'react'
import { Handler, viewportResizeDimension } from 'rrweb/typings/types'
import { useActions, useValues } from 'kea'
import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'
import { SessionPlayerState, SessionRecordingPlayerProps } from '~/types'
import { IconPlay } from 'scenes/session-recordings/player/icons'
import useSize from '@react-hook/size'
import { IconErrorOutline } from 'lib/components/icons'
import { LemonButton } from 'lib/components/LemonButton'

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
        let content = null
        if (currentPlayerState === SessionPlayerState.ERROR) {
            content = (
                <div className="flex flex-col justify-center items-center p-6 bg-white rounded m-6 gap-2 max-w-120 shadow">
                    <IconErrorOutline className="text-danger text-5xl" />
                    <div className="font-bold text-default text-lg">We're unable to play this recording</div>
                    <div className="text-muted text-sm text-center">
                        An error occurred that is preventing this recording from being played. You can refresh the page
                        to reload the recording.
                    </div>
                    <LemonButton
                        onClick={() => {
                            window.location.reload()
                        }}
                        type="primary"
                        fullWidth
                        center
                    >
                        Reload
                    </LemonButton>
                    <LemonButton
                        targetBlank
                        to="https://posthog.com/support?utm_medium=in-product&utm_campaign=recording-not-found"
                        type="secondary"
                        fullWidth
                        center
                    >
                        Contact support
                    </LemonButton>
                </div>
            )
        }
        if (currentPlayerState === SessionPlayerState.BUFFER) {
            content = <div className="text-4xl text-white">Buffering...</div>
        }
        if (currentPlayerState === SessionPlayerState.PAUSE) {
            content = <IconPlay className="rrweb-overlay-icon text-white" />
        }
        if (currentPlayerState === SessionPlayerState.SKIP) {
            content = <div className="text-4xl text-white">Skipping inactivity</div>
        }
        return content ? (
            <div className="rrweb-overlay justify-center absolute flex items-center h-full w-full cursor-pointer">
                {content}
            </div>
        ) : null
    }

    return (
        <div ref={containerRef} className="rrweb-player ph-no-capture" onClick={togglePlayPause}>
            <div className="player-frame" ref={ref} style={{ position: 'absolute' }} />
            <div className="rrweb-overlay-container">{renderPlayerState()}</div>
        </div>
    )
})
