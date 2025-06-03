import { IconPause, IconPlay, IconRewindPlay } from '@posthog/icons'
import { useActions, useValues } from 'kea'
import { useResizeBreakpoints } from 'lib/hooks/useResizeObserver'
import { IconComment, IconFullScreen } from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { PlayerUpNext } from 'scenes/session-recordings/player/PlayerUpNext'
import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'

import { KeyboardShortcut } from '~/layout/navigation-3000/components/KeyboardShortcut'
import { SessionPlayerState } from '~/types'

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
            icon={<IconFullScreen className="text-2xl" />}
            data-attr={isFullScreen ? 'exit-full-screen' : 'full-screen'}
        />
    )
}

function AnnotateRecording(): JSX.Element {
    const { setIsAnnotating } = useActions(sessionRecordingPlayerLogic)
    const { isAnnotating } = useValues(sessionRecordingPlayerLogic)

    return (
        <LemonButton
            size="xsmall"
            onClick={() => setIsAnnotating(!isAnnotating)}
            tooltip={isAnnotating ? 'Stop commenting' : 'Comment on this recording'}
            data-attr={isAnnotating ? 'stop-annotating-recording' : 'annotate-recording'}
            active={isAnnotating}
            icon={<IconComment className="text-xl" />}
        >
            Comment
        </LemonButton>
    )
}

export function PlayerController(): JSX.Element {
    const { playlistLogic } = useValues(sessionRecordingPlayerLogic)

    const { ref, size } = useResizeBreakpoints({
        0: 'small',
        600: 'normal',
    })

    return (
        <div className="bg-surface-primary flex flex-col select-none">
            <Seekbar />
            <div className="w-full px-2 py-1 relative flex items-center justify-center" ref={ref}>
                <div className="absolute left-2">
                    <Timestamp size={size} />
                </div>
                <div className="flex gap-0.5 items-center justify-center">
                    <SeekSkip direction="backward" />
                    <PlayPauseButton />
                    <SeekSkip direction="forward" />
                </div>
                <div className="absolute right-2 flex justify-end items-center">
                    <AnnotateRecording />
                    {playlistLogic ? <PlayerUpNext playlistLogic={playlistLogic} /> : undefined}
                    <FullScreen />
                </div>
            </div>
        </div>
    )
}
