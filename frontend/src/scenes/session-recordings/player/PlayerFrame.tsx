import './PlayerFrame.scss'

import useSize from '@react-hook/size'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { Handler, viewportResizeDimension } from 'posthog-js/rrweb-types'
import { useCallback, useEffect, useRef } from 'react'

import { getPlayerFrameScale, isIOS } from 'scenes/session-recordings/player/playerFrameScaling'
import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'

const BASE_CLICK_INDICATOR_DURATION_S = 1 / 3

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
    const { player, sessionRecordingId, maskingWindow, speed, resolution, playerFrameLoadRetries } =
        useValues(sessionRecordingPlayerLogic)
    const { setScale, setRootFrame, playerFrameDocumentLoadFailed } = useActions(sessionRecordingPlayerLogic)

    // A frame loads again only when its src changes, so each retry adds a query string the server ignores.
    const frameSrc = playerFrameLoadRetries ? `${PLAYER_FRAME_SRC}?retry=${playerFrameLoadRetries}` : PLAYER_FRAME_SRC

    const iframeRef = useRef<HTMLIFrameElement | null>(null)
    // rrweb's mount point, which lives in the player frame's document rather than this one.
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
            // this container. The parent is the player frame's body.
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
    // masking overlay are applied to that document.
    const applyFrameStyles = useCallback((): void => {
        iframeRef.current?.contentDocument?.documentElement?.style?.setProperty(
            '--player-frame-click-duration',
            `${BASE_CLICK_INDICATOR_DURATION_S / speed}s`
        )
        frameRef.current?.classList?.toggle('PlayerFrame__content--masking-window', !!maskingWindow)
    }, [speed, maskingWindow])

    const handleFrameLoad = useCallback((): void => {
        const frameDocument = iframeRef.current?.contentDocument
        const content = frameDocument?.getElementById(PLAYER_FRAME_CONTENT_ID)
        if (!content) {
            // Firefox fires load for the frame's initial about:blank document, and a load event for a
            // previous document arrives while the shell is still parsing, which is common in a hidden tab.
            // The shell is still on its way in both cases, and its own load event follows.
            if (frameDocument?.URL === 'about:blank' || (frameDocument && frameDocument.readyState !== 'complete')) {
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
        const timer = setTimeout(() => {
            if (!frameRef.current) {
                playerFrameDocumentLoadFailed(iframeRef.current)
            }
        }, PLAYER_FRAME_LOAD_TIMEOUT_MS)
        return () => clearTimeout(timer)
    }, [frameSrc, playerFrameDocumentLoadFailed])

    // Need useEffect to populate replayer on component paint. On the first paint the frame is still
    // loading, in which case handleFrameLoad does this instead.
    useEffect(() => {
        if (frameRef.current) {
            setRootFrame(frameRef.current)
        }
    }, [sessionRecordingId, setRootFrame])

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
        <div ref={containerRef} className={clsx('PlayerFrame ph-no-capture', isIOS() && 'PlayerFrame--ios')}>
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
        </div>
    )
}
