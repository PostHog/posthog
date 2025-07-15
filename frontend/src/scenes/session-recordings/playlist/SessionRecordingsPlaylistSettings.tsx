import { IconEllipsis, IconSort, IconTrash } from '@posthog/icons'
import { useActions, useValues } from 'kea'
import { SettingsBar, SettingsMenu } from 'scenes/session-recordings/components/PanelSettings'
import { RecordingUniversalFilters } from '~/types'
import { playerSettingsLogic } from '../player/playerSettingsLogic'
import {
    MAX_SELECTED_RECORDINGS,
    DELETE_CONFIRMATION_TEXT,
    sessionRecordingsPlaylistLogic,
} from './sessionRecordingsPlaylistLogic'
import { savedSessionRecordingPlaylistsLogic } from 'scenes/session-recordings/saved-playlists/savedSessionRecordingPlaylistsLogic'
import { ReplayTabs } from '~/types'
import { LemonBadge, LemonButton, LemonCheckbox, LemonInput, LemonModal } from '@posthog/lemon-ui'
import { LemonMenuItem } from 'lib/lemon-ui/LemonMenu/LemonMenu'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'

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

function ConfirmDeleteRecordings({ shortId }: { shortId?: string }): JSX.Element {
    const { selectedRecordingsIds, isDeleteSelectedRecordingsDialogOpen, deleteConfirmationText } =
        useValues(sessionRecordingsPlaylistLogic)
    const { setIsDeleteSelectedRecordingsDialogOpen, setDeleteConfirmationText, handleDeleteSelectedRecordings } =
        useActions(sessionRecordingsPlaylistLogic)

    const handleClose = (): void => {
        setIsDeleteSelectedRecordingsDialogOpen(false)
        setDeleteConfirmationText('')
    }

    return (
        <LemonModal
            isOpen={isDeleteSelectedRecordingsDialogOpen}
            onClose={handleClose}
            title="Confirm deletion"
            maxWidth="500px"
        >
            <div className="space-y-4">
                <h4>
                    Are you sure you want to delete {selectedRecordingsIds.length} recording
                    {selectedRecordingsIds.length > 1 ? 's' : ''}?
                </h4>
                <div className="space-y-2">
                    <label className="text-sm">
                        To confirm, please type <strong>{DELETE_CONFIRMATION_TEXT}</strong> below:
                    </label>
                    <LemonInput
                        value={deleteConfirmationText}
                        onChange={setDeleteConfirmationText}
                        placeholder={DELETE_CONFIRMATION_TEXT}
                        className="w-full"
                        autoFocus
                    />
                </div>
                <div className="bg-warning-highlight border border-warning rounded p-2 text-sm">
                    This action cannot be undone. Deleting recordings doesn't affect your billing.
                </div>
            </div>
            <div className="flex justify-end gap-2 mt-4">
                <LemonButton type="secondary" onClick={handleClose}>
                    Cancel
                </LemonButton>
                <LemonButton
                    type="primary"
                    disabledReason={
                        deleteConfirmationText !== DELETE_CONFIRMATION_TEXT
                            ? 'Please type the correct confirmation text'
                            : undefined
                    }
                    onClick={() => handleDeleteSelectedRecordings(shortId)}
                >
                    Delete
                </LemonButton>
            </div>
        </LemonModal>
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
    const { featureFlags } = useValues(featureFlagLogic)
    const { autoplayDirection } = useValues(playerSettingsLogic)
    const { setAutoplayDirection } = useActions(playerSettingsLogic)
    const { playlists, playlistsLoading } = useValues(
        savedSessionRecordingPlaylistsLogic({ tab: ReplayTabs.Playlists })
    )
    const { selectedRecordingsIds, sessionRecordings, pinnedRecordings } = useValues(sessionRecordingsPlaylistLogic)
    const {
        handleBulkAddToPlaylist,
        handleBulkDeleteFromPlaylist,
        handleSelectUnselectAll,
        setIsDeleteSelectedRecordingsDialogOpen,
    } = useActions(sessionRecordingsPlaylistLogic)

    const recordings = type === 'filters' ? sessionRecordings : pinnedRecordings
    const checked = recordings.length > 0 && selectedRecordingsIds.length === recordings.length

    const getActionsMenuItems = (): LemonMenuItem[] => {
        const menuItems = []

        if (!playlistsLoading) {
            const collections =
                type === 'collection' && shortId
                    ? playlists.results.filter((playlist) => playlist.short_id !== shortId)
                    : playlists.results

            if (collections.length > 0) {
                menuItems.push({
                    label: 'Add to collection',
                    items: collections.map((playlist) => ({
                        label: <span className="truncate">{playlist.name || playlist.derived_name || 'Unnamed'}</span>,
                        onClick: () => handleBulkAddToPlaylist(playlist.short_id),
                    })),
                    'data-attr': 'add-to-collection',
                })
            }
        }

        if (type === 'collection' && shortId) {
            menuItems.push({
                label: 'Remove from this collection',
                onClick: () => handleBulkDeleteFromPlaylist(shortId),
                'data-attr': 'remove-from-collection',
            })
        }

        if (featureFlags[FEATURE_FLAGS.REPLAY_BULK_DELETE_SELECTED_RECORDINGS]) {
            menuItems.push({
                label: 'Delete',
                onClick: () => setIsDeleteSelectedRecordingsDialogOpen(true),
                icon: <IconTrash />,
                'data-attr': 'delete-recordings',
                status: 'danger' as const,
            })
        }

        return menuItems
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
            <ConfirmDeleteRecordings shortId={shortId} />
        </SettingsBar>
    )
}
