import {
    IconClock,
    IconEllipsis,
    IconHourglass,
    IconMouse,
    IconPause,
    IconPlay,
    IconRabbit,
    IconSearch,
    IconTortoise,
} from '@posthog/icons'
import useSize from '@react-hook/size'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { IconFullScreen, IconSync } from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonMenuItem } from 'lib/lemon-ui/LemonMenu'
import { humanFriendlyDuration } from 'lib/utils'
import { useEffect, useRef, useState } from 'react'
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

import { PlayerInspectorButton } from '../PlayerInspectorButton'
import { SeekSkip, Timestamp } from './PlayerControllerTime'
import { Seekbar } from './Seekbar'

function SetPlaybackSpeed(): JSX.Element {
    const { speed, sessionPlayerData } = useValues(sessionRecordingPlayerLogic)
    const { setSpeed } = useActions(sessionRecordingPlayerLogic)
    return (
        <SettingsMenu
            icon={
                speed === 0.5 ? (
                    <IconTortoise className="text-lg" style={{ stroke: 'currentColor', strokeWidth: '0.5' }} />
                ) : (
                    <IconRabbit className="text-lg" style={{ stroke: 'currentColor', strokeWidth: '0.5' }} />
                )
            }
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
            label={`Speed ${speed}x`}
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
            icon={<IconHourglass />}
        />
    )
}

function SetTimeFormat(): JSX.Element {
    const { timestampFormat } = useValues(playerSettingsLogic)
    const { setTimestampFormat } = useActions(playerSettingsLogic)

    return (
        <SettingsMenu
            matchWidth={true}
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
            title="Inspect the DOM as it was at this moment in the session. Analyze the structure and elements captured during the recording."
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

export function PlayerBottomSettings(): JSX.Element {
    const {
        logicProps: { noInspector },
    } = useValues(sessionRecordingPlayerLogic)
    const { showMouseTail, skipInactivitySetting, timestampFormat } = useValues(playerSettingsLogic)
    const { setShowMouseTail, setSkipInactivitySetting, setTimestampFormat } = useActions(playerSettingsLogic)

    const containerRef = useRef<HTMLDivElement | null>(null)
    const [width] = useSize(containerRef)

    const [isSmall, setIsSmall] = useState(false)
    useEffect(() => {
        if (!width) {
            // probably a false alarm or 0 on boot up we should ignore it
            return
        }
        const isSmallNow = width < 600
        const breakpointChanged = isSmall !== isSmallNow

        if (breakpointChanged) {
            setIsSmall(width < 600)
        }
    }, [width])

    const menuItems: LemonMenuItem[] = [
        isSmall
            ? {
                  label: TimestampFormatToLabel[timestampFormat],
                  icon: <IconClock />,
                  'data-attr': 'time-format-in-menu',
                  matchWidth: true,

                  items: [
                      {
                          label: 'UTC',
                          onClick: () => setTimestampFormat(TimestampFormat.UTC),
                          active: timestampFormat === TimestampFormat.UTC,
                          size: 'xsmall',
                      },
                      {
                          label: 'Device',
                          onClick: () => setTimestampFormat(TimestampFormat.Device),
                          active: timestampFormat === TimestampFormat.Device,
                          size: 'xsmall',
                      },
                      {
                          label: 'Relative',
                          onClick: () => setTimestampFormat(TimestampFormat.Relative),
                          active: timestampFormat === TimestampFormat.Relative,
                          size: 'xsmall',
                      },
                  ],
              }
            : undefined,
        isSmall
            ? {
                  label: 'Skip inactivity',
                  active: skipInactivitySetting,
                  'data-attr': 'skip-inactivity-in-menu',
                  onClick: () => setSkipInactivitySetting(!skipInactivitySetting),
                  icon: <IconHourglass />,
              }
            : undefined,
        {
            // title: "Show a tail following the cursor to make it easier to see",
            label: 'Show mouse tail',
            active: showMouseTail,
            'data-attr': 'show-mouse-tail-in-menu',
            onClick: () => setShowMouseTail(!showMouseTail),
            icon: <IconMouse className="text-lg" />,
        },
    ].filter(Boolean) as LemonMenuItem[]

    return (
        <SettingsBar border="top">
            <div className="no-flex sm:flex w-full justify-between items-center gap-0.5" ref={containerRef}>
                <div className="flex flex-row gap-0.5 h-full items-center">
                    <SetPlaybackSpeed />
                    {!isSmall && <SetTimeFormat />}
                    {!isSmall && <SkipInactivity />}

                    <SettingsMenu
                        icon={<IconEllipsis />}
                        items={menuItems}
                        highlightWhenActive={false}
                        closeOnClickInside={false}
                    />
                </div>
                <div className="flex flex-row gap-0.5">
                    {noInspector ? null : <InspectDOM />}
                    <PlayerInspectorButton />
                </div>
            </div>
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

export function PlayerController(): JSX.Element {
    const { playlistLogic } = useValues(sessionRecordingPlayerLogic)

    return (
        <div className="bg-surface-primary flex flex-col select-none">
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
                    <FullScreen />
                </div>
            </div>
        </div>
    )
}
