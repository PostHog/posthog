import { IconClock, IconCollapse45, IconExpand45, IconPause, IconPlay, IconSearch } from '@posthog/icons'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { useKeyboardHotkeys } from 'lib/hooks/useKeyboardHotkeys'
import { IconFullScreen, IconSync } from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { humanFriendlyDuration } from 'lib/utils'
import {
    SettingsBar,
    SettingsButton,
    SettingsMenu,
    SettingsToggle,
} from 'scenes/session-recordings/components/PanelSettings'
import { playerSettingsLogic, TimestampFormat } from 'scenes/session-recordings/player/playerSettingsLogic'
import { PlayerUpNext } from 'scenes/session-recordings/player/PlayerUpNext'
import {
    PLAYBACK_SPEEDS,
    sessionRecordingPlayerLogic,
} from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'
import { TimestampFormatToLabel } from 'scenes/session-recordings/utils'

import { KeyboardShortcut } from '~/layout/navigation-3000/components/KeyboardShortcut'
import { SessionPlayerState } from '~/types'

import { SeekSkip, Timestamp } from './PlayerControllerTime'
import { Seekbar } from './Seekbar'

function SetPlaybackSpeed(): JSX.Element {
    const { speed, sessionPlayerData } = useValues(sessionRecordingPlayerLogic)
    const { setSpeed } = useActions(sessionRecordingPlayerLogic)
    return (
        <SettingsMenu
            data-attr="session-recording-speed-select"
            items={PLAYBACK_SPEEDS.map((speedToggle) => ({
                label: (
                    <div className="flex w-full space-x-2 justify-between">
                        <span>{speedToggle}x</span>
                        <span>({humanFriendlyDuration(sessionPlayerData.durationMs / speedToggle / 1000)})</span>
                    </div>
                ),
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
            title="Show a tail following the cursor to make it easier to see"
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
            title="Skip inactivite parts of the recording"
            label="Skip inactivity"
            active={skipInactivitySetting}
            data-attr="skip-inactivity"
            onClick={() => setSkipInactivitySetting(!skipInactivitySetting)}
        />
    )
}

function SetTimeFormat(): JSX.Element {
    const { timestampFormat } = useValues(playerSettingsLogic)
    const { setTimestampFormat } = useActions(playerSettingsLogic)

    return (
        <SettingsMenu
            highlightWhenActive={false}
            items={[
                {
                    label: 'UTC',
                    onClick: () => setTimestampFormat(TimestampFormat.UTC),
                    active: timestampFormat === TimestampFormat.UTC,
                },
                {
                    label: 'Device',
                    onClick: () => setTimestampFormat(TimestampFormat.Device),
                    active: timestampFormat === TimestampFormat.Device,
                },
                {
                    label: 'Relative',
                    onClick: () => setTimestampFormat(TimestampFormat.Relative),
                    active: timestampFormat === TimestampFormat.Relative,
                },
            ]}
            icon={<IconClock />}
            label={TimestampFormatToLabel[timestampFormat]}
        />
    )
}

function InspectDOM(): JSX.Element {
    const { sessionPlayerMetaData } = useValues(sessionRecordingPlayerLogic)
    const { openExplorer } = useActions(sessionRecordingPlayerLogic)

    return (
        <SettingsButton
            title="View the DOM at this point in time in the recording"
            label="Inspect DOM"
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
        <SettingsBar border="top" className="justify-between">
            <div className="flex flex-row gap-0.5">
                <SkipInactivity />
                <ShowMouseTail />
                <SetPlaybackSpeed />
                <SetTimeFormat />
            </div>
            <InspectDOM />
        </SettingsBar>
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
                    {!isFullScreen ? 'Go' : 'Exit'} full screen <KeyboardShortcut f />
                </>
            }
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
            tooltip={
                <>
                    {isMaximised ? 'Open' : 'Close'} other panels <KeyboardShortcut m />
                </>
            }
            icon={isMaximised ? <IconCollapse45 className="text-lg" /> : <IconExpand45 className="text-lg" />}
        />
    )
}

export function PlayerController(): JSX.Element {
    const { playlistLogic } = useValues(sessionRecordingPlayerLogic)

    return (
        <div className="bg-bg-light flex flex-col select-none">
            <Seekbar />
            <div className="w-full px-2 py-1 relative flex items-center justify-center">
                <div className="absolute left-2">
                    <Timestamp />
                </div>
                <div className="flex gap-0.5 items-center justify-center">
                    <SeekSkip direction="backward" />
                    <PlayPauseButton />
                    <SeekSkip direction="forward" />
                </div>
                <div className="absolute right-2 flex justify-end items-center">
                    {playlistLogic ? <PlayerUpNext playlistLogic={playlistLogic} /> : undefined}
                    <Maximise />
                    <FullScreen />
                </div>
            </div>

            <PlayerBottomSettings />
        </div>
    )
}
