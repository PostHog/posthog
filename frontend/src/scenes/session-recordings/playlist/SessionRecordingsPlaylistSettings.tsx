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
import { LemonBadge, LemonButton, LemonCheckbox, LemonInput, LemonModal, Spinner } from '@posthog/lemon-ui'
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

function getLabel(filters: RecordingUniversalFilters): string {
    const order_field = filters.order || 'start_time'
    if (order_field === 'start_time') {
        return filters.order_direction === 'ASC' ? 'Oldest' : 'Latest'
    }

    return SortingKeyToLabel[order_field as keyof typeof SortingKeyToLabel]
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
                    label: 'Start time',
                    items: [
                        {
                            label: 'Latest',
                            onClick: () => setFilters({ order: 'start_time', order_direction: 'DESC' }),
                            active:
                                !filters.order || (filters.order === 'start_time' && filters.order_direction !== 'ASC'),
                        },
                        {
                            label: 'Oldest',
                            onClick: () => setFilters({ order: 'start_time', order_direction: 'ASC' }),
                            active: filters.order === 'start_time' && filters.order_direction === 'ASC',
                        },
                    ],
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
            label={getLabel(filters)}
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

function NewCollectionModal(): JSX.Element {
    const { isNewCollectionDialogOpen, selectedRecordingsIds, newCollectionName } =
        useValues(sessionRecordingsPlaylistLogic)
    const { setIsNewCollectionDialogOpen, setNewCollectionName, handleCreateNewCollectionBulkAdd } =
        useActions(sessionRecordingsPlaylistLogic)
    const { loadPlaylists } = useActions(savedSessionRecordingPlaylistsLogic({ tab: ReplayTabs.Playlists }))

    const handleClose = (): void => {
        setIsNewCollectionDialogOpen(false)
        setNewCollectionName('')
    }

    return (
        <LemonModal isOpen={isNewCollectionDialogOpen} onClose={handleClose} title="Create collection" maxWidth="500px">
            <div className="space-y-4">
                <p>
                    Collections help you organize and save recordings for later analysis. This will create a new
                    collection with the {selectedRecordingsIds.length} selected recording
                    {selectedRecordingsIds.length > 1 ? 's' : ''}.
                </p>
                <div className="space-y-2">
                    <label className="text-sm font-medium">Collection name</label>
                    <LemonInput
                        value={newCollectionName}
                        onChange={setNewCollectionName}
                        placeholder="e.g., Bug reports, User onboarding, Feature usage"
                        className="w-full"
                        autoFocus
                    />
                </div>
            </div>

            <div className="flex justify-end gap-2 mt-8">
                <LemonButton type="secondary" onClick={handleClose}>
                    Cancel
                </LemonButton>
                <LemonButton
                    type="primary"
                    disabledReason={newCollectionName.length === 0 ? 'Collection name is required' : undefined}
                    onClick={() => handleCreateNewCollectionBulkAdd(loadPlaylists)}
                >
                    Create collection
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
        setIsNewCollectionDialogOpen,
        handleBulkMarkAsViewed,
        handleBulkMarkAsNotViewed,
    } = useActions(sessionRecordingsPlaylistLogic)

    const recordings = type === 'filters' ? sessionRecordings : pinnedRecordings
    const checked = recordings.length > 0 && selectedRecordingsIds.length === recordings.length

    const getActionsMenuItems = (): LemonMenuItem[] => {
        const menuItems: LemonMenuItem[] = [
            {
                label: 'Add to new collection...',
                onClick: () => setIsNewCollectionDialogOpen(true),
                'data-attr': 'add-to-new-collection',
            },
        ]

        const collections =
            type === 'collection' && shortId
                ? playlists.results.filter((playlist) => playlist.short_id !== shortId)
                : playlists.results

        menuItems.push({
            label: 'Add to collection',
            items: playlistsLoading
                ? [
                      {
                          label: <Spinner textColored={true} />,
                          onClick: () => {},
                      },
                  ]
                : collections.map((playlist) => ({
                      label: <span className="truncate">{playlist.name || playlist.derived_name || 'Unnamed'}</span>,
                      onClick: () => handleBulkAddToPlaylist(playlist.short_id),
                  })),
            disabledReason: collections.length === 0 ? 'There are no collections' : undefined,
            'data-attr': 'add-to-collection',
        })

        if (type === 'collection' && shortId) {
            menuItems.push({
                label: 'Remove from this collection',
                onClick: () => handleBulkDeleteFromPlaylist(shortId),
                'data-attr': 'remove-from-collection',
            })
        }

        menuItems.push({
            label: 'Mark as viewed',
            onClick: () => handleBulkMarkAsViewed(shortId),
            'data-attr': 'mark-as-viewed',
        })

        menuItems.push({
            label: 'Mark as not viewed',
            onClick: () => handleBulkMarkAsNotViewed(shortId),
            'data-attr': 'mark-as-not-viewed',
        })

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
                        data-attr="bulk-action-menu"
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
            <NewCollectionModal />
        </SettingsBar>
    )
}
