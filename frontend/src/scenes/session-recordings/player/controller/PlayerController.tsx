import { useActions, useValues } from 'kea'

import { IconCamera, IconPause, IconRewindPlay, IconVideoCamera } from '@posthog/icons'
import { LemonButton, LemonTag } from '@posthog/lemon-ui'

import { useResizeBreakpoints } from 'lib/hooks/useResizeObserver'
import { IconFullScreen } from 'lib/lemon-ui/icons'
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

function GhostIcon(props: { className: string }): JSX.Element {
    return (
        <svg className={props.className} xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor">
            <path d="M12 2C15.5 2 18 5 19 8C22 9 23 11.73 23 14L20.2253 14.7928C19.796 14.9154 19.5 15.3078 19.5 15.7543V17.25C19.5 18.2165 18.7165 19 17.75 19H17.1536C16.4825 19 15.8562 19.3366 15.4858 19.8962C14.5576 21.2987 13.3957 22 12 22C10.6043 22 9.44238 21.2987 8.5142 19.8962C8.14383 19.3366 7.51746 19 6.84636 19H6.25C5.2835 19 4.5 18.2165 4.5 17.25V15.7543C4.5 15.3078 4.20402 14.9154 3.77472 14.7928L1 14C1 11.7337 2 9 5 8C6 5 8.5 2 12 2ZM12 4C9.8906 4 7.93534 5.78788 6.98864 8.37148L6.89737 8.63246L6.58114 9.58114L5.63246 9.89737C4.37721 10.3158 3.56485 11.238 3.20834 12.4564L3.185 12.543L4.32416 12.8697C5.55353 13.221 6.41845 14.3095 6.49454 15.5727L6.5 15.7543V17H6.84636C8.1096 17 9.29359 17.5963 10.0461 18.5996L10.182 18.7925C10.7584 19.6634 11.3162 20 12 20C12.6382 20 13.1667 19.7068 13.7029 18.9596L13.818 18.7925C14.5151 17.739 15.6658 17.0807 16.9178 17.0069L17.1536 17H17.5V15.7543C17.5 14.4757 18.309 13.3451 19.5027 12.9249L19.6758 12.8697L20.815 12.543L20.7918 12.4555C20.4554 11.3047 19.7124 10.4193 18.5728 9.97176L18.3675 9.89737L17.4189 9.58114L17.1026 8.63246C16.1948 5.90906 14.1797 4 12 4ZM12 12C12.8284 12 13.5 13.1193 13.5 14.5C13.5 15.8807 12.8284 17 12 17C11.1716 17 10.5 15.8807 10.5 14.5C10.5 13.1193 11.1716 12 12 12ZM9.5 8C10.3284 8 11 8.67157 11 9.5C11 10.3284 10.3284 11 9.5 11C8.67157 11 8 10.3284 8 9.5C8 8.67157 8.67157 8 9.5 8ZM14.5 8C15.3284 8 16 8.67157 16 9.5C16 10.3284 15.3284 11 14.5 11C13.6716 11 13 10.3284 13 9.5C13 8.67157 13.6716 8 14.5 8Z" />
        </svg>
    )
}

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
                <IconPause className="text-3xl" />
            ) : endReached ? (
                <IconRewindPlay className="text-3xl" />
            ) : (
                <GhostIcon className="LemonIcon text-3xl" /> //TODO: After halloween, reset to <IconPlay className="text-3xl" />
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
