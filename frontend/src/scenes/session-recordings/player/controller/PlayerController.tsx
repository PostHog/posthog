import { useActions, useValues } from 'kea'
import { useEffect, useRef, useState } from 'react'

import { IconCamera, IconPause, IconPlay, IconRewindPlay } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { isChristmas, isHalloween } from 'lib/holidays'
import { useKeyboardHotkeys } from 'lib/hooks/useKeyboardHotkeys'
import { useResizeBreakpoints } from 'lib/hooks/useResizeObserver'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { IconFullScreen, IconGhost, IconSanta, IconSkipEnd, IconSkipStart } from 'lib/lemon-ui/icons'
import { cn } from 'lib/utils/css-classes'
import {
    CommentOnRecordingButton,
    EmojiCommentOnRecordingButton,
} from 'scenes/session-recordings/player/commenting/CommentOnRecordingButton'
import {
    ModesWithInteractions,
    SessionRecordingPlayerMode,
    sessionRecordingPlayerLogic,
} from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'

import { KeyboardShortcut } from '~/layout/navigation-3000/components/KeyboardShortcut'
import { SessionPlayerState } from '~/types'

import { ClipRecording } from './ClipRecording'
import { SeekSkip, Timestamp } from './PlayerControllerTime'
import { Seekbar } from './Seekbar'

function PlayPauseButton(): JSX.Element {
    const { playingState, endReached } = useValues(sessionRecordingPlayerLogic)
    const { togglePlayPause } = useActions(sessionRecordingPlayerLogic)

    const showPause = playingState === SessionPlayerState.PLAY

    const getPlayIcon = (): JSX.Element => {
        // If between October 28th and October 31st
        if (isHalloween()) {
            return <IconGhost className="text-3xl" />
        }

        // If between December 1st and December 28th
        if (isChristmas()) {
            return <IconSanta className="text-3xl" />
        }

        return <IconPlay className="text-3xl" />
    }

    return (
        <LemonButton
            size="large"
            noPadding={true}
            onClick={togglePlayPause}
            tooltip={
                <div className="flex gap-1">
                    <span>{showPause ? 'Pause' : endReached ? 'Restart' : 'Play'}</span>
                    <KeyboardShortcut space />
                </div>
            }
            data-attr={showPause ? 'recording-pause' : endReached ? 'recording-rewind' : 'recording-play'}
        >
            {showPause ? (
                <IconPause className="text-3xl" />
            ) : endReached ? (
                <IconRewindPlay className="text-3xl" />
            ) : (
                getPlayIcon()
            )}
        </LemonButton>
    )
}

function FullScreen(): JSX.Element {
    const { isFullScreen } = useValues(sessionRecordingPlayerLogic)
    const { setIsFullScreen } = useActions(sessionRecordingPlayerLogic)
    return (
        <LemonButton
            size="xsmall"
            onClick={() => setIsFullScreen(!isFullScreen)}
            tooltip={
                <>
                    <span>{!isFullScreen ? 'Go' : 'Exit'}</span> full screen <KeyboardShortcut f />
                </>
            }
            icon={<IconFullScreen className="text-xl" />}
            data-attr={isFullScreen ? 'exit-full-screen' : 'full-screen'}
        />
    )
}

function SkipToStart(): JSX.Element {
    const { seekToStart } = useActions(sessionRecordingPlayerLogic)

    return (
        <LemonButton
            size="small"
            noPadding={true}
            onClick={seekToStart}
            tooltip="Go to start"
            data-attr="recording-skip-to-start"
        >
            <IconSkipStart className="text-2xl" />
        </LemonButton>
    )
}

function SkipToNext(): JSX.Element | null {
    const timeoutRef = useRef<NodeJS.Timeout>()
    const { endReached, playNextAnimationInterrupted, playNextRecording } = useValues(sessionRecordingPlayerLogic)
    const { reportNextRecordingTriggered, setPlayNextAnimationInterrupted } = useActions(sessionRecordingPlayerLogic)
    const [animate, setAnimate] = useState(false)

    useKeyboardHotkeys(
        {
            n: {
                action: () => {
                    if (playNextRecording) {
                        reportNextRecordingTriggered(false)
                        playNextRecording(false)
                    }
                },
            },
        },
        [playNextRecording]
    )

    const goToRecording = (automatic: boolean): void => {
        if (!playNextRecording) {
            return
        }
        reportNextRecordingTriggered(automatic)
        playNextRecording(automatic)
    }

    useEffect(() => {
        clearTimeout(timeoutRef.current)

        if (endReached && playNextRecording) {
            setAnimate(true)
            setPlayNextAnimationInterrupted(false)
            timeoutRef.current = setTimeout(() => {
                goToRecording(true)
            }, 3000)
        }

        return () => clearTimeout(timeoutRef.current)
    }, [endReached, !!playNextRecording]) // eslint-disable-line react-hooks/exhaustive-deps

    useEffect(() => {
        if (playNextAnimationInterrupted) {
            clearTimeout(timeoutRef.current)
            setAnimate(false)
        }
    }, [playNextAnimationInterrupted])

    if (!playNextRecording) {
        return null
    }

    return (
        <Tooltip
            title={
                <>
                    Play the next recording <KeyboardShortcut n />
                </>
            }
        >
            <LemonButton
                size="small"
                noPadding={true}
                onClick={() => goToRecording(false)}
                data-attr="recording-skip-to-next"
                className={cn('SkipToNextButton', animate && 'SkipToNextButton--animating')}
            >
                <IconSkipEnd className="text-2xl" />
            </LemonButton>
        </Tooltip>
    )
}

export function Screenshot({ className }: { className?: string }): JSX.Element {
    const { takeScreenshot } = useActions(sessionRecordingPlayerLogic)

    return (
        <LemonButton
            size="xsmall"
            onClick={(e) => {
                e.stopPropagation()
                takeScreenshot()
            }}
            tooltip={
                <>
                    Take a screenshot of this point in the recording <KeyboardShortcut s />
                </>
            }
            icon={<IconCamera className={cn('text-xl', className)} />}
            data-attr="replay-screenshot-png"
            tooltipPlacement="top"
        />
    )
}

export function PlayerController(): JSX.Element {
    const { logicProps, hoverModeIsEnabled, showPlayerChrome } = useValues(sessionRecordingPlayerLogic)

    const playerMode = logicProps.mode ?? SessionRecordingPlayerMode.Standard

    const { ref, size } = useResizeBreakpoints({
        0: 'small',
        600: 'normal',
    })

    return (
        <div
            className={cn(
                'flex flex-col select-none',
                hoverModeIsEnabled ? 'absolute bottom-0 left-0 right-0 transition-all duration-25 ease-in-out' : '',
                hoverModeIsEnabled && showPlayerChrome
                    ? 'opacity-100 bg-surface-primary pointer-events-auto'
                    : hoverModeIsEnabled
                      ? 'opacity-0 pointer-events-none'
                      : 'bg-surface-primary'
            )}
        >
            <Seekbar />
            <div className="w-full px-2 py-1 relative flex items-center justify-between" ref={ref}>
                <div className="flex gap-0.5 items-center justify-center">
                    <SeekSkip direction="backward" />
                    <PlayPauseButton />
                    <SeekSkip direction="forward" />
                    <Timestamp size={size} />
                </div>
                <div className="flex gap-0.5 justify-end items-center">
                    {ModesWithInteractions.includes(playerMode) && (
                        <>
                            <CommentOnRecordingButton />
                            <EmojiCommentOnRecordingButton />
                            <Screenshot />
                            <ClipRecording />
                        </>
                    )}
                    <SkipToStart />
                    <SkipToNext />
                    <FullScreen />
                </div>
            </div>
        </div>
    )
}
