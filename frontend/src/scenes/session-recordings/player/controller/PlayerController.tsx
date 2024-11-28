import { IconCollapse45, IconExpand45, IconPause, IconPlay, IconSearch } from '@posthog/icons'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { useKeyboardHotkeys } from 'lib/hooks/useKeyboardHotkeys'
import { IconFullScreen, IconSync } from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { SettingsMenu, SettingsToggle } from 'scenes/session-recordings/components/PanelSettings'
import { playerSettingsLogic } from 'scenes/session-recordings/player/playerSettingsLogic'
import {
    PLAYBACK_SPEEDS,
    sessionRecordingPlayerLogic,
} from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'

import { KeyboardShortcut } from '~/layout/navigation-3000/components/KeyboardShortcut'
import { SessionPlayerState } from '~/types'

import { SeekSkip, Timestamp } from './PlayerControllerTime'
import { Seekbar } from './Seekbar'

function SetPlaybackSpeed(): JSX.Element {
    const { speed } = useValues(sessionRecordingPlayerLogic)
    const { setSpeed } = useActions(sessionRecordingPlayerLogic)
    return (
        <SettingsMenu
            data-attr="session-recording-speed-select"
            items={PLAYBACK_SPEEDS.map((speedToggle) => ({
                label: `${speedToggle}x`,
                onClick: () => setSpeed(speedToggle),
                active: speed === speedToggle && speedToggle !== 1,
                status: speed === speedToggle ? 'danger' : 'default',
            }))}
            label={`${speed}x`}
        />
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
                <IconPause className="text-2xl" />
            ) : endReached ? (
                <IconSync className="text-2xl" />
            ) : (
                <IconPlay className="text-2xl" />
            )}
        </LemonButton>
    )
}

function ShowMouseTail(): JSX.Element {
    const { showMouseTail } = useValues(playerSettingsLogic)
    const { setShowMouseTail } = useActions(playerSettingsLogic)

    return (
        <SettingsToggle
            title="Show mouse tail"
            label="Show mouse tail"
            active={showMouseTail}
            data-attr="show-mouse-tail"
            onClick={() => setShowMouseTail(!showMouseTail)}
        />
    )
}

function SkipInactivity(): JSX.Element {
    const { skipInactivitySetting } = useValues(playerSettingsLogic)
    const { setSkipInactivitySetting } = useActions(playerSettingsLogic)

    return (
        <SettingsToggle
            title="Skip inactivity"
            label="Skip inactivity"
            active={skipInactivitySetting}
            data-attr="skip-inactivity"
            onClick={() => setSkipInactivitySetting(!skipInactivitySetting)}
        />
    )
}

function InspectDOM(): JSX.Element {
    const { explorerMode, sessionPlayerMetaData } = useValues(sessionRecordingPlayerLogic)
    const { openExplorer } = useActions(sessionRecordingPlayerLogic)

    return (
        <SettingsToggle
            title="View the DOM at this point in time in the recording"
            label="Inspect DOM"
            active={!!explorerMode}
            data-attr="explore-dom"
            onClick={() => openExplorer()}
            disabledReason={
                sessionPlayerMetaData?.snapshot_source === 'web' ? undefined : 'Only available for web recordings'
            }
            icon={<IconSearch />}
        />
    )
}

function PlayerBottomSettings(): JSX.Element {
    return (
        <div className="flex flex-row bg-bg-3000 w-full overflow-hidden border-t font-light text-small">
            <SkipInactivity />
            <ShowMouseTail />
            <SetPlaybackSpeed />
            <InspectDOM />
        </div>
    )
}

function FullScreen(): JSX.Element {
    const { isFullScreen } = useValues(sessionRecordingPlayerLogic)
    const { setIsFullScreen } = useActions(sessionRecordingPlayerLogic)
    return (
        <LemonButton
            size="xsmall"
            onClick={() => setIsFullScreen(!isFullScreen)}
            tooltip={`${!isFullScreen ? 'Go' : 'Exit'} full screen (F)`}
        >
            <IconFullScreen className={clsx('text-2xl', isFullScreen ? 'text-link' : 'text-primary-alt')} />
        </LemonButton>
    )
}

function Maximise(): JSX.Element {
    const { sidebarOpen, playlistOpen } = useValues(playerSettingsLogic)
    const { setSidebarOpen, setPlaylistOpen } = useActions(playerSettingsLogic)

    const isMaximised = !sidebarOpen && !playlistOpen

    function onChangeMaximise(): void {
        setPlaylistOpen(isMaximised)
        setSidebarOpen(isMaximised)
    }

    useKeyboardHotkeys(
        {
            m: {
                action: onChangeMaximise,
            },
        },
        []
    )

    return (
        <LemonButton
            size="xsmall"
            onClick={onChangeMaximise}
            tooltip={`${isMaximised ? 'Open' : 'Close'} other panels (M)`}
            icon={isMaximised ? <IconCollapse45 /> : <IconExpand45 />}
            className="text-2xl"
        />
    )
}

export function PlayerController(): JSX.Element {
    return (
        <div className="bg-bg-light flex flex-col select-none">
            <Seekbar />
            <div className="w-full flex flex-row gap-0.5 px-2 py-1 items-center">
                <div className="flex flex-row flex-1 gap-2 justify-start">
                    <Timestamp />

                    <div className="flex gap-0.5 items-center justify-center">
                        <SeekSkip direction="backward" />
                        <PlayPauseButton />
                        <SeekSkip direction="forward" />
                    </div>
                </div>
                <div className="flex justify-items-end">
                    <Maximise />
                    <FullScreen />
                </div>
            </div>
            <PlayerBottomSettings />
        </div>
    )
}
