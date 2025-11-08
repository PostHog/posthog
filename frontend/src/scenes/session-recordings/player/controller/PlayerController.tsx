import { useActions, useValues } from 'kea'

import { IconCamera, IconPause, IconPlay, IconRewindPlay, IconVideoCamera } from '@posthog/icons'
import { LemonButton, LemonTag } from '@posthog/lemon-ui'

import { useResizeBreakpoints } from 'lib/hooks/useResizeObserver'
import { IconFullScreen, IconGhost, IconSanta } from 'lib/lemon-ui/icons'
import { cn } from 'lib/utils/css-classes'
import { PlayerUpNext } from 'scenes/session-recordings/player/PlayerUpNext'
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

import { playerSettingsLogic } from '../playerSettingsLogic'
import { ClipRecording } from './ClipRecording'
import { SeekSkip, Timestamp } from './PlayerControllerTime'
import { Seekbar } from './Seekbar'

function PlayPauseButton(): JSX.Element {
    const { playingState, endReached } = useValues(sessionRecordingPlayerLogic)
    const { togglePlayPause } = useActions(sessionRecordingPlayerLogic)

    const showPause = playingState === SessionPlayerState.PLAY

    const getPlayIcon = (): JSX.Element => {
        const localTime = new Date()

        // If between October 28th and October 31st
        if (localTime.getMonth() == 9 && localTime.getDate() >= 28) {
            return <IconGhost className="text-3xl" />
        }

        // If between December 1st and December 28th
        if (localTime.getMonth() == 11 && localTime.getDate() <= 28) {
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

function CinemaMode(): JSX.Element {
    const { isCinemaMode, sidebarOpen } = useValues(playerSettingsLogic)
    const { setIsCinemaMode, setSidebarOpen } = useActions(playerSettingsLogic)

    const handleCinemaMode = (): void => {
        setIsCinemaMode(!isCinemaMode)
        if (sidebarOpen) {
            setSidebarOpen(false)
        }
    }

    return (
        <>
            {isCinemaMode && <LemonTag type="success">You are in "Cinema mode"</LemonTag>}
            <LemonButton
                size="xsmall"
                onClick={handleCinemaMode}
                tooltip={
                    <>
                        <span>{!isCinemaMode ? 'Enter' : 'Exit'}</span> cinema mode <KeyboardShortcut t />
                    </>
                }
                status={isCinemaMode ? 'danger' : 'default'}
                icon={<IconVideoCamera className="text-xl" />}
                data-attr={isCinemaMode ? 'exit-cinema-mode' : 'cinema-mode'}
            />
        </>
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
    const { playlistLogic, logicProps, hoverModeIsEnabled, showPlayerChrome } = useValues(sessionRecordingPlayerLogic)
    const { isCinemaMode } = useValues(playerSettingsLogic)

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
                <Timestamp size={size} />
                <div className="flex gap-0.5 items-center justify-center">
                    <SeekSkip direction="backward" />
                    <PlayPauseButton />
                    <SeekSkip direction="forward" />
                </div>
                <div className="flex justify-end items-center">
                    {!isCinemaMode && ModesWithInteractions.includes(playerMode) && (
                        <>
                            <CommentOnRecordingButton />
                            <EmojiCommentOnRecordingButton />
                            <Screenshot />
                            <ClipRecording />
                        </>
                    )}
                    {playlistLogic && ModesWithInteractions.includes(playerMode) ? (
                        <PlayerUpNext playlistLogic={playlistLogic} />
                    ) : undefined}
                    {playerMode === SessionRecordingPlayerMode.Standard && <CinemaMode />}
                    <FullScreen />
                </div>
            </div>
        </div>
    )
}
