import './PlayerFrame.scss'
import './PlayerFrameLLMHighlight.scss'

import useSize from '@react-hook/size'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { Handler, viewportResizeDimension } from 'posthog-js/rrweb-types'
import { useCallback, useEffect, useRef } from 'react'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { getPlayerFrameScale, isIOS } from 'scenes/session-recordings/player/playerFrameScaling'
import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'

const BASE_CLICK_INDICATOR_DURATION_S = 1 / 3

// rrweb builds its replay iframe on about:blank, and a frame on a local scheme inherits its
// embedder's whole policy, report-uri included. Mounting rrweb inside a real document instead puts
// that document in the inheritance chain, so a recorded page is judged against its policy rather
// than the app's. CSPMiddleware supplies it.
const PLAYER_FRAME_SRC = '/replay_player_frame/index.html'
const PLAYER_FRAME_CONTENT_ID = 'player-frame-content'

export const PlayerFrame = (): JSX.Element => {
    const replayDimensionRef = useRef<viewportResizeDimension>()
    const { player, sessionRecordingId, maskingWindow, speed, resolution } = useValues(sessionRecordingPlayerLogic)
    const { setScale, setRootFrame } = useActions(sessionRecordingPlayerLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    const ownDocument = !!featureFlags[FEATURE_FLAGS.REPLAY_PLAYER_OWN_DOCUMENT]

    const iframeRef = useRef<HTMLIFrameElement | null>(null)
    // rrweb's mount point. Under the flag it lives in the player frame's document, not this one.
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

            // Under the flag the parent is the player frame's body, which fills this container
            // exactly, so it measures the same box either way.
            const parentDimensions = frameRef.current.parentElement.getBoundingClientRect()

            const { scale, transform } = getPlayerFrameScale(parentDimensions, dimensions)

            const wrapperStyle = player.replayer.wrapper.style
            if (transform === null) {
                wrapperStyle.removeProperty('transform')
            } else {
                wrapperStyle.setProperty('transform', transform)
            }

            setScale(scale)
        },
        [player, setScale, resolution]
    )

    const windowResize = useCallback((): void => {
        updatePlayerDimensions(replayDimensionRef.current)
    }, [updatePlayerDimensions])

    // The app stylesheet cannot reach inside the player frame, so the click duration and the
    // masking overlay are applied to that document rather than to the container below.
    const applyFrameStyles = useCallback((): void => {
        if (!ownDocument) {
            return
        }
        iframeRef.current?.contentDocument?.documentElement?.style?.setProperty(
            '--player-frame-click-duration',
            `${BASE_CLICK_INDICATOR_DURATION_S / speed}s`
        )
        frameRef.current?.classList?.toggle('PlayerFrame__content--masking-window', !!maskingWindow)
    }, [ownDocument, speed, maskingWindow])

    const handleFrameLoad = useCallback((): void => {
        const content = iframeRef.current?.contentDocument?.getElementById(PLAYER_FRAME_CONTENT_ID)
        if (!content) {
            return
        }
        frameRef.current = content as HTMLDivElement
        // The frame usually loads after speed and maskingWindow settle, so the effect below has
        // already run against a document that did not exist yet.
        applyFrameStyles()
        setRootFrame(frameRef.current)
    }, [setRootFrame, applyFrameStyles])

    // Need useEffect to populate replayer on component paint. Under the flag the frame may still be
    // loading, in which case handleFrameLoad does this instead.
    // ownDocument is a dependency because flags resolve after the first paint. A user who holds a
    // stale enabled flag paints the frame, then React swaps in the container below when the fresh
    // value arrives, and the replayer must move with it.
    useEffect(() => {
        if (frameRef.current) {
            setRootFrame(frameRef.current)
        }
    }, [sessionRecordingId, ownDocument, setRootFrame])

    useEffect(() => {
        applyFrameStyles()
    }, [applyFrameStyles])

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
            className={clsx('PlayerFrame ph-no-capture PlayerFrame--llm-highlight', isIOS() && 'PlayerFrame--ios')}
            style={
                {
                    '--player-frame-click-duration': `${BASE_CLICK_INDICATOR_DURATION_S / speed}s`,
                } as React.CSSProperties
            }
        >
            {ownDocument ? (
                <iframe
                    ref={iframeRef}
                    className="PlayerFrame__document"
                    src={PLAYER_FRAME_SRC}
                    onLoad={handleFrameLoad}
                    title="Session replay player"
                    // Interaction belongs to the app's controls, not the recorded page.
                    sandbox="allow-same-origin"
                />
            ) : (
                <div
                    className={clsx('PlayerFrame__content', maskingWindow && 'PlayerFrame__content--masking-window')}
                    ref={frameRef}
                />
            )}
        </div>
    )
}
