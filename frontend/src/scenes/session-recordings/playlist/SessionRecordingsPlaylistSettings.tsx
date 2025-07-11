import { IconEllipsis, IconSort } from '@posthog/icons'
import { useActions, useValues } from 'kea'
import { SettingsBar, SettingsMenu } from 'scenes/session-recordings/components/PanelSettings'
import { RecordingUniversalFilters } from '~/types'
import { playerSettingsLogic } from '../player/playerSettingsLogic'
import { MAX_SELECTED_RECORDINGS, sessionRecordingsPlaylistLogic } from './sessionRecordingsPlaylistLogic'
import { savedSessionRecordingPlaylistsLogic } from 'scenes/session-recordings/saved-playlists/savedSessionRecordingPlaylistsLogic'
import { ReplayTabs } from '~/types'
import { LemonBadge, LemonCheckbox } from '@posthog/lemon-ui'
import { LemonMenuItem } from 'lib/lemon-ui/LemonMenu/LemonMenu'

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

export function SessionRecordingsPlaylistTopSettings({
    filters,
    setFilters,
    type = 'filters',
    shortId,
}: {
    filters?: RecordingUniversalFilters
    setFilters?: (filters: Partial<RecordingUniversalFilters>) => void
    type?: 'filters' | 'collection'
    shortId?: string
}): JSX.Element {
    const { autoplayDirection } = useValues(playerSettingsLogic)
    const { setAutoplayDirection } = useActions(playerSettingsLogic)
    const { playlists, playlistsLoading } = useValues(
        savedSessionRecordingPlaylistsLogic({ tab: ReplayTabs.Playlists })
    )
    const { selectedRecordingsIds, sessionRecordings, pinnedRecordings } = useValues(sessionRecordingsPlaylistLogic)
    const { handleBulkAddToPlaylist, handleBulkDeleteFromPlaylist, handleSelectUnselectAll } =
        useActions(sessionRecordingsPlaylistLogic)

    const recordings = type === 'filters' ? sessionRecordings : pinnedRecordings
    const checked = recordings.length > 0 && selectedRecordingsIds.length === recordings.length

    const getActionsMenuItems = (): LemonMenuItem[] => {
        if (type === 'collection' && shortId) {
            return [
                {
                    label: 'Remove from collection',
                    onClick: () => handleBulkDeleteFromPlaylist(shortId),
                    'data-attr': 'remove-from-collection',
                },
            ]
        }

        if (!playlistsLoading && playlists.results.length > 0) {
            return [
                {
                    label: 'Add to collection',
                    items: playlists.results.map((playlist) => ({
                        label: <span className="truncate">{playlist.name || playlist.derived_name || 'Unnamed'}</span>,
                        onClick: () => handleBulkAddToPlaylist(playlist.short_id),
                    })),
                    'data-attr': 'add-to-collection',
                },
            ]
        }

        return []
    }

    return (
        <SettingsBar border="none" className="justify-between">
            <div className="flex items-center">
                <LemonCheckbox
                    disabledReason={
                        recordings.length > MAX_SELECTED_RECORDINGS
                            ? `Cannot select more than ${MAX_SELECTED_RECORDINGS} recordings at once`
                            : undefined
                    }
                    checked={checked}
                    onChange={(checked) => handleSelectUnselectAll(checked, type)}
                    stopPropagation
                    className="ml-2"
                    dataAttr="select-all-recordings"
                    aria-label="Select all recordings"
                />
                {filters && setFilters ? (
                    <span className="text-xs font-normal inline-flex items-center ml-2">
                        Sort by: <SortedBy filters={filters} setFilters={setFilters} />
                    </span>
                ) : null}
            </div>
            <div className="flex items-center">
                {selectedRecordingsIds.length > 0 && (
                    <SettingsMenu
                        items={getActionsMenuItems()}
                        label={<LemonBadge content={selectedRecordingsIds.length.toString()} size="small" />}
                    />
                )}
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
                    ]}
                    icon={<IconEllipsis className="rotate-90" />}
                />
            </div>
        </SettingsBar>
    )
}
