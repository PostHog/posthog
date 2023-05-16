import './SessionRecordingPlayer.scss'
import { useMemo, useState } from 'react'
import { BindLogic, useActions, useValues } from 'kea'
import {
    ONE_FRAME_MS,
    PLAYBACK_SPEEDS,
    sessionRecordingPlayerLogic,
    SessionRecordingPlayerLogicProps,
} from './sessionRecordingPlayerLogic'
import { PlayerFrame } from 'scenes/session-recordings/player/PlayerFrame'
import { PlayerController } from 'scenes/session-recordings/player/PlayerController'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { PlayerInspector } from 'scenes/session-recordings/player/inspector/PlayerInspector'
import { PlayerMeta } from './PlayerMeta'
import { sessionRecordingDataLogic } from './sessionRecordingDataLogic'
import clsx from 'clsx'
import { HotkeysInterface, useKeyboardHotkeys } from 'lib/hooks/useKeyboardHotkeys'
import { usePageVisibility } from 'lib/hooks/usePageVisibility'
import { RecordingNotFound } from 'scenes/session-recordings/player/RecordingNotFound'
import { useResizeBreakpoints } from 'lib/hooks/useResizeObserver'
import { PlayerFrameOverlay } from './PlayerFrameOverlay'
import { SessionRecordingPlayerExplorer } from './view-explorer/SessionRecordingPlayerExplorer'

export interface SessionRecordingPlayerProps extends SessionRecordingPlayerLogicProps {
    includeMeta?: boolean
    noBorder?: boolean
}

export const createPlaybackSpeedKey = (action: (val: number) => void): HotkeysInterface => {
    return PLAYBACK_SPEEDS.map((x, i) => ({ key: `${i}`, value: x })).reduce(
        (acc, x) => ({ ...acc, [x.key]: { action: () => action(x.value) } }),
        {}
    )
}

export function SessionRecordingPlayer(props: SessionRecordingPlayerProps): JSX.Element {
    const {
        sessionRecordingId,
        sessionRecordingData,
        playerKey,
        includeMeta = true,
        recordingStartTime, // While optional, including recordingStartTime allows the underlying ClickHouse query to be much faster
        matching,
        noBorder = false,
        autoPlay = true,
        nextSessionRecording,
    } = props

    const logicProps: SessionRecordingPlayerLogicProps = {
        sessionRecordingId,
        playerKey,
        matching,
        sessionRecordingData,
        recordingStartTime,
        autoPlay,
        nextSessionRecording,
    }
    const { setIsFullScreen, setPause, togglePlayPause, seekBackward, seekForward, setSpeed, closeExplorer } =
        useActions(sessionRecordingPlayerLogic(logicProps))
    const { isNotFound } = useValues(sessionRecordingDataLogic(logicProps))
    const { isFullScreen, explorerMode } = useValues(sessionRecordingPlayerLogic(logicProps))
    const speedHotkeys = useMemo(() => createPlaybackSpeedKey(setSpeed), [setSpeed])

    useKeyboardHotkeys(
        {
            f: {
                action: () => setIsFullScreen(!isFullScreen),
            },
            space: {
                action: () => togglePlayPause(),
            },
            arrowleft: {
                action: (e) => {
                    console.log(e)
                    if (e.ctrlKey || e.metaKey) {
                        return
                    }
                    e.preventDefault()
                    e.altKey && setPause()
                    seekBackward(e.altKey ? ONE_FRAME_MS : undefined)
                },
                willHandleEvent: true,
            },
            arrowright: {
                action: (e) => {
                    if (e.ctrlKey || e.metaKey) {
                        return
                    }
                    e.preventDefault()
                    e.altKey && setPause()
                    seekForward(e.altKey ? ONE_FRAME_MS : undefined)
                },
                willHandleEvent: true,
            },
            ...speedHotkeys,
            ...(isFullScreen ? { escape: { action: () => setIsFullScreen(false) } } : {}),
        },
        [isFullScreen]
    )

    usePageVisibility((pageIsVisible) => {
        if (!pageIsVisible) {
            setPause()
        }
    })

    const { ref, size } = useResizeBreakpoints({
        0: 'small',
        1000: 'medium',
    })

    const [inspectorFocus, setInspectorFocus] = useState(false)

    if (isNotFound) {
        return (
            <div className="text-center">
                <RecordingNotFound />
            </div>
        )
    }

    return (
        <BindLogic logic={sessionRecordingPlayerLogic} props={logicProps}>
            <div
                ref={ref}
                className={clsx('SessionRecordingPlayer', {
                    'SessionRecordingPlayer--fullscreen': isFullScreen,
                    'SessionRecordingPlayer--no-border': noBorder,
                    'SessionRecordingPlayer--widescreen': !isFullScreen && size !== 'small',
                    'SessionRecordingPlayer--explorer-mode': !!explorerMode,
                    'SessionRecordingPlayer--inspector-focus': inspectorFocus,
                })}
            >
                <div className="SessionRecordingPlayer__main">
                    {includeMeta || isFullScreen ? <PlayerMeta /> : null}
                    <div className="SessionRecordingPlayer__body">
                        <PlayerFrame />
                        <PlayerFrameOverlay />
                    </div>
                    <LemonDivider className="my-0" />
                    <PlayerController />
                </div>
                <PlayerInspector onFocusChange={setInspectorFocus} />

                {explorerMode && <SessionRecordingPlayerExplorer {...explorerMode} onClose={() => closeExplorer()} />}
            </div>
        </BindLogic>
    )
}
