import { IconEllipsis } from '@posthog/icons'
import { IconClock, IconSort } from '@posthog/icons'
import { useActions, useValues } from 'kea'
import { SettingsBar, SettingsMenu, SettingsToggle } from 'scenes/session-recordings/components/PanelSettings'
import { TimestampFormatToLabel } from 'scenes/session-recordings/utils'

import { RecordingUniversalFilters } from '~/types'

import { PlaybackMode, playerSettingsLogic, TimestampFormat } from '../player/playerSettingsLogic'

const SortingKeyToLabel = {
    start_time: 'Latest',
    activity_score: 'Activity',
    console_error_count: 'Errors',
    duration: 'Total duration',
    active_seconds: 'Activity',
    inactive_seconds: 'Inactivity',
    click_count: 'Clicks',
    keypress_count: 'Keystrokes',
    mouse_activity_count: 'Mouse activity',
}

function SortedBy({
    filters,
    setFilters,
}: {
    filters: RecordingUniversalFilters
    setFilters: (filters: Partial<RecordingUniversalFilters>) => void
}): JSX.Element {
    return (
        <SettingsMenu
            highlightWhenActive={false}
            items={[
                {
                    label: SortingKeyToLabel['start_time'],
                    onClick: () => setFilters({ order: 'start_time' }),
                    active: filters.order === 'start_time',
                },
                {
                    label: SortingKeyToLabel['activity_score'],
                    onClick: () => setFilters({ order: 'activity_score' }),
                    active: filters.order === 'activity_score',
                },
                {
                    label: SortingKeyToLabel['console_error_count'],
                    onClick: () => setFilters({ order: 'console_error_count' }),
                    active: filters.order === 'console_error_count',
                },
                {
                    label: 'Longest',
                    items: [
                        {
                            label: SortingKeyToLabel['duration'],
                            onClick: () => setFilters({ order: 'duration' }),
                            active: filters.order === 'duration',
                        },
                        {
                            label: SortingKeyToLabel['active_seconds'],
                            onClick: () => setFilters({ order: 'active_seconds' }),
                            active: filters.order === 'active_seconds',
                        },
                        {
                            label: SortingKeyToLabel['inactive_seconds'],
                            onClick: () => setFilters({ order: 'inactive_seconds' }),
                            active: filters.order === 'inactive_seconds',
                        },
                    ],
                },
                {
                    label: 'Most active',
                    items: [
                        {
                            label: SortingKeyToLabel['click_count'],
                            onClick: () => setFilters({ order: 'click_count' }),
                            active: filters.order === 'click_count',
                        },
                        {
                            label: SortingKeyToLabel['keypress_count'],
                            onClick: () => setFilters({ order: 'keypress_count' }),
                            active: filters.order === 'keypress_count',
                        },
                        {
                            label: SortingKeyToLabel['mouse_activity_count'],
                            onClick: () => setFilters({ order: 'mouse_activity_count' }),
                            active: filters.order === 'mouse_activity_count',
                        },
                    ],
                },
            ]}
            icon={<IconSort className="text-lg" />}
            label={SortingKeyToLabel[filters.order || 'start_time']}
        />
    )
}

export function SessionRecordingPlaylistBottomSettings(): JSX.Element {
    const { hideViewedRecordings, playlistTimestampFormat } = useValues(playerSettingsLogic)
    const { setHideViewedRecordings, setPlaylistTimestampFormat } = useActions(playerSettingsLogic)
    return (
        <SettingsBar border="top">
            <SettingsToggle
                active={hideViewedRecordings}
                title="Hide viewed recordings"
                label="Hide viewed recordings"
                onClick={() => setHideViewedRecordings(!hideViewedRecordings)}
            />
            <SettingsMenu
                highlightWhenActive={false}
                items={[
                    {
                        label: 'UTC',
                        onClick: () => setPlaylistTimestampFormat(TimestampFormat.UTC),
                        active: playlistTimestampFormat === TimestampFormat.UTC,
                    },
                    {
                        label: 'Device',
                        onClick: () => setPlaylistTimestampFormat(TimestampFormat.Device),
                        active: playlistTimestampFormat === TimestampFormat.Device,
                    },
                    {
                        label: 'Relative',
                        onClick: () => setPlaylistTimestampFormat(TimestampFormat.Relative),
                        active: playlistTimestampFormat === TimestampFormat.Relative,
                    },
                ]}
                icon={<IconClock />}
                label={TimestampFormatToLabel[playlistTimestampFormat]}
            />
        </SettingsBar>
    )
}

export function SessionRecordingsPlaylistTopSettings({
    filters,
    setFilters,
}: {
    filters?: RecordingUniversalFilters
    setFilters?: (filters: Partial<RecordingUniversalFilters>) => void
}): JSX.Element {
    const { autoplayDirection, playbackMode } = useValues(playerSettingsLogic)
    const { setAutoplayDirection, setPlaybackMode } = useActions(playerSettingsLogic)

    return (
        <SettingsBar border="none" className="justify-end">
            {filters && setFilters ? <SortedBy filters={filters} setFilters={setFilters} /> : null}
            <SettingsMenu
                items={[
                    {
                        label: 'Autoplay',
                        items: [
                            {
                                label: 'Off',
                                onClick: () => setAutoplayDirection(null),
                                active: !autoplayDirection,
                            },
                            {
                                label: 'Newer recordings',
                                onClick: () => setAutoplayDirection('newer'),
                                active: autoplayDirection === 'newer',
                            },
                            {
                                label: 'Older recordings',
                                onClick: () => setAutoplayDirection('older'),
                                active: autoplayDirection === 'older',
                            },
                        ],
                    },
                    {
                        label: 'Playback mode',
                        items: [
                            {
                                label: 'Recordings',
                                onClick: () => setPlaybackMode(PlaybackMode.Recording),
                                active: playbackMode === PlaybackMode.Recording,
                            },
                            {
                                label: 'Waterfall',
                                onClick: () => setPlaybackMode(PlaybackMode.Waterfall),
                                active: playbackMode === PlaybackMode.Waterfall,
                            },
                        ],
                    },
                ]}
                icon={<IconEllipsis className="rotate-90" />}
            />
        </SettingsBar>
    )
}
