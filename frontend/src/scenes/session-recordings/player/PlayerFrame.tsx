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
// Dividing the indicator by playback speed alone leaves 21ms at 16x, about one rendered frame, so a
// click flashes past before a viewer can see it. Hold a floor above the ~100ms a flash needs.
const MIN_CLICK_INDICATOR_DURATION_S = 0.15

const clickIndicatorDuration = (speed: number): string =>
    `${Math.max(BASE_CLICK_INDICATOR_DURATION_S / speed, MIN_CLICK_INDICATOR_DURATION_S)}s`

// rrweb builds its replay iframe on about:blank, and a frame on a local scheme inherits its
// embedder's whole policy, report-uri included. Mounting rrweb inside a real document instead puts
// that document in the inheritance chain, so a recorded page is judged against its policy rather
// than the app's. CSPMiddleware supplies it.
const PLAYER_FRAME_SRC = '/replay_player_frame/index.html'
const PLAYER_FRAME_CONTENT_ID = 'player-frame-content'
// Without a timeout, a frame load event that never arrives leaves rrweb with nowhere to mount and
// the player stays blank for as long as the tab is open.
const PLAYER_FRAME_LOAD_TIMEOUT_MS = 10000

export const PlayerFrame = (): JSX.Element => {
    const replayDimensionRef = useRef<viewportResizeDimension>()
    const {
        player,
        sessionRecordingId,
        maskingWindow,
        speed,
        resolution,
        playerFrameDocumentFailed,
        playerFrameLoadRetries,
    } = useValues(sessionRecordingPlayerLogic)
    const { setScale, setRootFrame, playerFrameDocumentLoadFailed } = useActions(sessionRecordingPlayerLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    // A frame that loaded without its mount node falls back to the container below, which is the
    // flag-off path. That path still works, so the player renders rather than staying blank.
    const ownDocument = !!featureFlags[FEATURE_FLAGS.REPLAY_PLAYER_OWN_DOCUMENT] && !playerFrameDocumentFailed

    // A frame loads again only when its src changes, so each retry adds a query string the server ignores.
    const frameSrc = playerFrameLoadRetries ? `${PLAYER_FRAME_SRC}?retry=${playerFrameLoadRetries}` : PLAYER_FRAME_SRC

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

            // rrweb scales its wrapper to fit the wrapper's parent, so measure that parent rather than
            // this container. Under the flag the parent is the player frame's body.
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
            clickIndicatorDuration(speed)
        )
        frameRef.current?.classList?.toggle('PlayerFrame__content--masking-window', !!maskingWindow)
    }, [ownDocument, speed, maskingWindow])

    const handleFrameLoad = useCallback((): void => {
        const frameDocument = iframeRef.current?.contentDocument
        const content = frameDocument?.getElementById(PLAYER_FRAME_CONTENT_ID)
        if (!content) {
            if (frameDocument?.URL === 'about:blank') {
                // Firefox fires load for the frame's initial about:blank document. The shell document
                // is still on its way, so this load says nothing about it.
                return
            }
            // A same-origin error page, a login redirect, and a browser error page all fire load too,
            // so a load event does not prove the shell document arrived.
            playerFrameDocumentLoadFailed(iframeRef.current)
            return
        }
        frameRef.current = content as HTMLDivElement
        // The frame usually loads after speed and maskingWindow settle, so the effect below has
        // already run against a document that did not exist yet.
        applyFrameStyles()
        setRootFrame(frameRef.current)
    }, [setRootFrame, applyFrameStyles, playerFrameDocumentLoadFailed])

    // frameSrc is a dependency so each retry, which swaps the frame's document, arms its own
    // timeout instead of reusing the one armed for the previous document.
    useEffect(() => {
        if (!ownDocument) {
            return
        }
        const timer = setTimeout(() => {
            if (!frameRef.current) {
                playerFrameDocumentLoadFailed(iframeRef.current)
            }
        }, PLAYER_FRAME_LOAD_TIMEOUT_MS)
        return () => clearTimeout(timer)
    }, [ownDocument, frameSrc, playerFrameDocumentLoadFailed])

    // Need useEffect to populate replayer on component paint. Under the flag the frame may still be
    // loading, in which case handleFrameLoad does this instead.
    // ownDocument is a dependency because flags resolve after the first paint. A user who holds a
    // stale enabled flag paints the frame, then React swaps in the container below when the fresh
    // value arrives, and the replayer must move with it. The fallback after a failed frame load
    // swaps the same way.
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
        <div
            ref={containerRef}
            className={clsx('PlayerFrame ph-no-capture PlayerFrame--llm-highlight', isIOS() && 'PlayerFrame--ios')}
            style={
                {
                    '--player-frame-click-duration': clickIndicatorDuration(speed),
                } as React.CSSProperties
            }
        >
            {ownDocument ? (
                <iframe
                    ref={iframeRef}
                    className="PlayerFrame__document"
                    src={frameSrc}
                    onLoad={handleFrameLoad}
                    title="Session replay player"
                    // Interaction belongs to the app's controls, not the recorded page.
                    // Do not add allow-scripts even though the browser reports it missing. That
                    // report is from rrweb's own replay frame, which carries the same sandbox and
                    // cannot inherit a permission it does not request, so it changes nothing a
                    // recording renders. It only lets this document, same-origin with the app, drop
                    // its own sandbox.
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
