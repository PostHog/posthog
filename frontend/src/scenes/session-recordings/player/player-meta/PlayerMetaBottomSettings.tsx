import { IconClock, IconEllipsis, IconHourglass, IconMouse, IconRabbit, IconSearch, IconTortoise } from '@posthog/icons'
import { useActions, useValues } from 'kea'
import { LemonMenuItem } from 'lib/lemon-ui/LemonMenu'
import { humanFriendlyDuration } from 'lib/utils'
import {
    SettingsBar,
    SettingsButton,
    SettingsMenu,
    SettingsToggle,
} from 'scenes/session-recordings/components/PanelSettings'
import { PlayerInspectorButton } from 'scenes/session-recordings/player/player-meta/PlayerInspectorButton'
import { PlayerMetaBreakpoints } from 'scenes/session-recordings/player/player-meta/PlayerMeta'
import { playerSettingsLogic, TimestampFormat } from 'scenes/session-recordings/player/playerSettingsLogic'
import {
    PLAYBACK_SPEEDS,
    sessionRecordingPlayerLogic,
} from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'
import { TimestampFormatToLabel } from 'scenes/session-recordings/utils'

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
                    <div className="flex w-full deprecated-space-x-2 justify-between">
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

function SkipInactivity(): JSX.Element {
    const { skipInactivitySetting } = useValues(playerSettingsLogic)
    const { setSkipInactivitySetting } = useActions(playerSettingsLogic)

    return (
        <SettingsToggle
            title="Skip inactive parts of the recording"
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

export function PlayerMetaBottomSettings({ size }: { size: PlayerMetaBreakpoints }): JSX.Element {
    const {
        logicProps: { noInspector },
    } = useValues(sessionRecordingPlayerLogic)
    const { showMouseTail, skipInactivitySetting, timestampFormat } = useValues(playerSettingsLogic)
    const { setShowMouseTail, setSkipInactivitySetting, setTimestampFormat } = useActions(playerSettingsLogic)
    const isSmall = size === 'small'

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
            <div className="flex w-full justify-between items-center gap-0.5">
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
