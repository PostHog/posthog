import { IconPause, IconPlay, IconRewindPlay, IconVideoCamera } from '@posthog/icons'
import { useActions, useValues } from 'kea'
import { useResizeBreakpoints } from 'lib/hooks/useResizeObserver'
import { IconFullScreen } from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { PlayerUpNext } from 'scenes/session-recordings/player/PlayerUpNext'
import {
    sessionRecordingPlayerLogic,
    SessionRecordingPlayerMode,
} from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'

import { KeyboardShortcut } from '~/layout/navigation-3000/components/KeyboardShortcut'
import { SessionPlayerState } from '~/types'

import { playerSettingsLogic } from '../playerSettingsLogic'
import { SeekSkip, Timestamp } from './PlayerControllerTime'
import { Seekbar } from './Seekbar'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { CommentOnRecordingButton } from 'scenes/session-recordings/player/commenting/CommentOnRecordingButton'
import { LemonTag } from 'lib/lemon-ui/LemonTag'

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
                        <span>{!isCinemaMode ? 'Enter' : 'Exit'}</span> cinema mode
                    </>
                }
                status={isCinemaMode ? 'danger' : 'default'}
                icon={<IconVideoCamera className="text-2xl" />}
                data-attr={isCinemaMode ? 'exit-zen-mode' : 'zen-mode'}
            />
        </>
    )
}

export function PlayerController(): JSX.Element {
    const { playlistLogic, logicProps } = useValues(sessionRecordingPlayerLogic)
    const { isCinemaMode } = useValues(playerSettingsLogic)
    const { featureFlags } = useValues(featureFlagLogic)

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
                            {playlistLogic ? <PlayerUpNext playlistLogic={playlistLogic} /> : undefined}
                        </>
                    )}
                    {featureFlags[FEATURE_FLAGS.REPLAY_ZEN_MODE] && <CinemaMode />}
                    <FullScreen />
                </div>
            </div>
        </div>
    )
}
