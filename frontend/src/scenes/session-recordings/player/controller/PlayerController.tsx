import { useActions, useValues } from 'kea'

import { IconCamera, IconPause, IconPlay, IconRewindPlay, IconVideoCamera } from '@posthog/icons'
import { LemonButton, LemonTag } from '@posthog/lemon-ui'

import { useResizeBreakpoints } from 'lib/hooks/useResizeObserver'
import { IconFullScreen } from 'lib/lemon-ui/icons'
import { PlayerUpNext } from 'scenes/session-recordings/player/PlayerUpNext'
import { CommentOnRecordingButton } from 'scenes/session-recordings/player/commenting/CommentOnRecordingButton'
import {
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
        >
            {showPause ? (
                <IconPause className="text-2xl" />
            ) : endReached ? (
                <IconRewindPlay className="text-2xl" />
            ) : (
                <IconPlay className="text-2xl" />
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

function Screenshot(): JSX.Element {
    const { takeScreenshot } = useActions(sessionRecordingPlayerLogic)

    return (
        <LemonButton
            size="xsmall"
            onClick={takeScreenshot}
            tooltip={
                <>
                    Take a screenshot of this point in the recording <KeyboardShortcut s />
                </>
            }
            icon={<IconCamera className="text-xl" />}
            data-attr="replay-screenshot-png"
            tooltipPlacement="top"
        />
    )
}

export function PlayerController(): JSX.Element {
    const { playlistLogic, logicProps } = useValues(sessionRecordingPlayerLogic)
    const { isCinemaMode } = useValues(playerSettingsLogic)

    const playerMode = logicProps.mode ?? SessionRecordingPlayerMode.Standard

    const { ref, size } = useResizeBreakpoints({
        0: 'small',
        600: 'normal',
    })

    return (
        <div className="bg-surface-primary flex flex-col select-none">
            <Seekbar />
            <div className="w-full px-2 py-1 relative flex items-center justify-between" ref={ref}>
                <Timestamp size={size} />
                <div className="flex gap-0.5 items-center justify-center">
                    <SeekSkip direction="backward" />
                    <PlayPauseButton />
                    <SeekSkip direction="forward" />
                </div>
                <div className="flex justify-end items-center">
                    {!isCinemaMode && playerMode === SessionRecordingPlayerMode.Standard && (
                        <>
                            <CommentOnRecordingButton />
                            <Screenshot />
                            <ClipRecording />
                            {playlistLogic ? <PlayerUpNext playlistLogic={playlistLogic} /> : undefined}
                        </>
                    )}
                    <CinemaMode />
                    <FullScreen />
                </div>
            </div>
        </div>
    )
}
