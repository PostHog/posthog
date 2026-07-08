import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import posthog from 'posthog-js'

import { IconChevronRight, IconEllipsis, IconEye, IconInfo, IconPlus, IconSort, IconTrash } from '@posthog/icons'
import { LemonBadge, LemonButton, LemonCheckbox, LemonInput, LemonModal, Spinner, Tooltip } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonMenu, LemonMenuItem } from 'lib/lemon-ui/LemonMenu/LemonMenu'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'
import { sessionRecordingCollectionsLogic } from 'scenes/session-recordings/collections/sessionRecordingCollectionsLogic'
import { SettingsBar, SettingsMenu } from 'scenes/session-recordings/components/PanelSettings'
import { urls } from 'scenes/urls'

import { AccessControlLevel, AccessControlResourceType, RecordingUniversalFilters } from '~/types'

import { bulkScanLogic } from 'products/replay_vision/frontend/logics/bulkScanLogic'
import { visionQuotaLogic } from 'products/replay_vision/frontend/logics/visionQuotaLogic'
import { quotaUx } from 'products/replay_vision/frontend/utils/quotaProjection'

import { playerSettingsLogic } from '../player/playerSettingsLogic'
import {
    DELETE_CONFIRMATION_TEXT,
    MAX_SELECTED_RECORDINGS,
    sessionRecordingsPlaylistLogic,
} from './sessionRecordingsPlaylistLogic'

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
    recording_ttl: 'Expiration',
    surfacing_score: 'Relevance',
}

const RELEVANCE_SORT_EXPLANATION =
    'Relevance predicts which sessions are worth watching, using signals like rage clicks, dead clicks, console errors, failed network requests, and in-session activity. The highest-scoring recordings appear first.'

function getLabel(filters: RecordingUniversalFilters): string {
    const order_field = filters.order || 'start_time'
    if (order_field === 'start_time') {
        return filters.order_direction === 'ASC' ? 'Oldest' : 'Latest'
    }

    return SortingKeyToLabel[order_field as keyof typeof SortingKeyToLabel]
}

type RecordingSort = { order: NonNullable<RecordingUniversalFilters['order']>; order_direction: 'ASC' | 'DESC' }

/** The analytics payload for a sort change, or null when the sort is unchanged so we don't log no-op switches. */
export function getSortChangedEvent(
    filters: RecordingUniversalFilters,
    sort: RecordingSort
): Record<string, string> | null {
    if (sort.order === filters.order && sort.order_direction === filters.order_direction) {
        return null
    }
    return {
        sort_key: sort.order,
        sort_direction: sort.order_direction,
        previous_sort_key: filters.order ?? 'start_time',
        previous_sort_direction: filters.order_direction ?? 'DESC',
    }
}

function SortedBy({
    filters,
    setFilters,
    disabledReason,
}: {
    filters: RecordingUniversalFilters
    setFilters: (filters: Partial<RecordingUniversalFilters>) => void
    disabledReason?: string
}): JSX.Element {
    const surfacingScoreEnabled = useFeatureFlag('REPLAY_PLAYLIST_SURFACING_SCORE')
    const inRelevanceSortExperiment = useFeatureFlag('REPLAY_PLAYLIST_RELEVANCE_SORT_EXPERIMENT', 'test')
    const showRelevanceSort = surfacingScoreEnabled || inRelevanceSortExperiment

    // Track sort changes for the relevance-sort experiment
    const changeSort = (sort: RecordingSort): void => {
        const sortChangedEvent = getSortChangedEvent(filters, sort)
        if (sortChangedEvent) {
            posthog.capture('session recording list sort changed', sortChangedEvent)
        }
        setFilters(sort)
    }

    return (
        <SettingsMenu
            highlightWhenActive={false}
            disabledReason={disabledReason}
            items={[
                ...(showRelevanceSort
                    ? [
                          {
                              label: SortingKeyToLabel['surfacing_score'],
                              tooltip: RELEVANCE_SORT_EXPLANATION,
                              onClick: () => changeSort({ order: 'surfacing_score', order_direction: 'DESC' }),
                              active: filters.order === 'surfacing_score',
                          },
                      ]
                    : []),
                {
                    label: 'Start time',
                    items: [
                        {
                            label: 'Latest',
                            onClick: () => changeSort({ order: 'start_time', order_direction: 'DESC' }),
                            active:
                                !filters.order || (filters.order === 'start_time' && filters.order_direction !== 'ASC'),
                        },
                        {
                            label: 'Oldest',
                            onClick: () => changeSort({ order: 'start_time', order_direction: 'ASC' }),
                            active: filters.order === 'start_time' && filters.order_direction === 'ASC',
                        },
                    ],
                },
                {
                    label: SortingKeyToLabel['activity_score'],
                    onClick: () => changeSort({ order: 'activity_score', order_direction: 'DESC' }),
                    active: filters.order === 'activity_score',
                },
                {
                    label: SortingKeyToLabel['console_error_count'],
                    onClick: () => changeSort({ order: 'console_error_count', order_direction: 'DESC' }),
                    active: filters.order === 'console_error_count',
                },
                {
                    label: 'Longest',
                    items: [
                        {
                            label: SortingKeyToLabel['duration'],
                            onClick: () => changeSort({ order: 'duration', order_direction: 'DESC' }),
                            active: filters.order === 'duration',
                        },
                        {
                            label: SortingKeyToLabel['active_seconds'],
                            onClick: () => changeSort({ order: 'active_seconds', order_direction: 'DESC' }),
                            active: filters.order === 'active_seconds',
                        },
                        {
                            label: SortingKeyToLabel['inactive_seconds'],
                            onClick: () => changeSort({ order: 'inactive_seconds', order_direction: 'DESC' }),
                            active: filters.order === 'inactive_seconds',
                        },
                    ],
                },
                {
                    label: 'Most active',
                    items: [
                        {
                            label: SortingKeyToLabel['click_count'],
                            onClick: () => changeSort({ order: 'click_count', order_direction: 'DESC' }),
                            active: filters.order === 'click_count',
                        },
                        {
                            label: SortingKeyToLabel['keypress_count'],
                            onClick: () => changeSort({ order: 'keypress_count', order_direction: 'DESC' }),
                            active: filters.order === 'keypress_count',
                        },
                        {
                            label: SortingKeyToLabel['mouse_activity_count'],
                            onClick: () => changeSort({ order: 'mouse_activity_count', order_direction: 'DESC' }),
                            active: filters.order === 'mouse_activity_count',
                        },
                    ],
                },
                {
                    label: 'Expiration',
                    onClick: () => changeSort({ order: 'recording_ttl', order_direction: 'ASC' }),
                    active: filters.order === 'recording_ttl',
                },
            ]}
            icon={<IconSort className="text-lg" />}
            label={
                filters.order === 'surfacing_score' ? (
                    <span className="inline-flex items-center gap-1">
                        {SortingKeyToLabel['surfacing_score']}
                        <Tooltip title={RELEVANCE_SORT_EXPLANATION}>
                            <IconInfo className="text-sm" />
                        </Tooltip>
                    </span>
                ) : (
                    getLabel(filters)
                )
            }
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

export function AddToCollectionModal({ shortId }: { shortId?: string }): JSX.Element {
    const {
        isAddToCollectionModalOpen,
        selectedRecordingsIds,
        addToCollectionSearch,
        collectionsForBulkAdd,
        collectionsForBulkAddLoading,
        isCreatingNewCollectionInModal,
        newCollectionName,
    } = useValues(sessionRecordingsPlaylistLogic)
    const {
        setIsAddToCollectionModalOpen,
        setAddToCollectionSearch,
        setIsCreatingNewCollectionInModal,
        setNewCollectionName,
        handleBulkAddToPlaylist,
        handleCreateNewCollectionBulkAdd,
    } = useActions(sessionRecordingsPlaylistLogic)
    const { loadPlaylists } = useActions(sessionRecordingCollectionsLogic)

    const accessControlDisabledReason = getAccessControlDisabledReason(
        AccessControlResourceType.SessionRecording,
        AccessControlLevel.Editor
    )

    const handleClose = (): void => {
        setIsAddToCollectionModalOpen(false)
    }

    const recordingCountSuffix = `${selectedRecordingsIds.length} recording${
        selectedRecordingsIds.length > 1 ? 's' : ''
    }`

    const collections = (collectionsForBulkAdd?.results ?? []).filter((p) => (shortId ? p.short_id !== shortId : true))

    return (
        <LemonModal
            isOpen={isAddToCollectionModalOpen}
            onClose={handleClose}
            title={isCreatingNewCollectionInModal ? 'Create collection' : 'Add to collection'}
            maxWidth="500px"
        >
            {!isCreatingNewCollectionInModal ? (
                <div className="space-y-3">
                    <p className="mb-0 text-secondary">Add {recordingCountSuffix} to an existing collection.</p>
                    <LemonInput
                        type="search"
                        placeholder="Search collections"
                        value={addToCollectionSearch}
                        onChange={setAddToCollectionSearch}
                        fullWidth
                        autoFocus
                    />
                    <div className="border border-primary rounded overflow-hidden">
                        <div className="max-h-80 overflow-y-auto">
                            {collectionsForBulkAddLoading ? (
                                <div className="p-4 text-center">
                                    <Spinner textColored />
                                </div>
                            ) : collections.length === 0 ? (
                                <div className="p-4 text-center text-secondary">
                                    {addToCollectionSearch ? 'No collections match your search' : 'No collections yet'}
                                </div>
                            ) : (
                                <ul className="m-0 p-0 list-none">
                                    {collections.map((playlist) => (
                                        <li key={playlist.short_id}>
                                            <LemonButton
                                                fullWidth
                                                size="small"
                                                disabledReason={accessControlDisabledReason}
                                                onClick={() => {
                                                    handleBulkAddToPlaylist(playlist.short_id)
                                                    handleClose()
                                                }}
                                                data-attr="add-to-existing-collection-item"
                                            >
                                                <div className="flex flex-col items-start w-full">
                                                    <span className="truncate w-full">
                                                        {playlist.name || playlist.derived_name || 'Unnamed'}
                                                    </span>
                                                    {playlist.last_modified_at ? (
                                                        <span className="text-xs text-secondary">
                                                            Updated {dayjs(playlist.last_modified_at).fromNow()}
                                                        </span>
                                                    ) : null}
                                                </div>
                                            </LemonButton>
                                        </li>
                                    ))}
                                </ul>
                            )}
                        </div>
                    </div>
                    <div className="flex justify-between items-center gap-2 mt-2">
                        <LemonButton
                            type="secondary"
                            icon={<IconPlus />}
                            onClick={() => setIsCreatingNewCollectionInModal(true)}
                            disabledReason={accessControlDisabledReason}
                            data-attr="add-to-new-collection"
                        >
                            New collection
                        </LemonButton>
                        <LemonButton type="secondary" onClick={handleClose}>
                            Cancel
                        </LemonButton>
                    </div>
                </div>
            ) : (
                <div className="space-y-4">
                    <p>
                        Collections help you organize and save recordings for later analysis. This will create a new
                        collection with the {recordingCountSuffix}.
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
                    <div className="flex justify-end gap-2 mt-8">
                        <LemonButton type="secondary" onClick={() => setIsCreatingNewCollectionInModal(false)}>
                            Back
                        </LemonButton>
                        <LemonButton
                            type="primary"
                            disabledReason={newCollectionName.length === 0 ? 'Collection name is required' : undefined}
                            onClick={() => handleCreateNewCollectionBulkAdd(loadPlaylists)}
                        >
                            Create collection
                        </LemonButton>
                    </div>
                </div>
            )}
        </LemonModal>
    )
}

/** Bulk "Scan these recordings" row whose scanner list opens on hover (a nested `items` menu is click-only). */
function BulkScanMenuItem(): JSX.Element {
    const { selectedRecordingsIds } = useValues(sessionRecordingsPlaylistLogic)
    const { scanners, scannersLoading, scanning } = useValues(bulkScanLogic)
    const { scanRecordings } = useActions(bulkScanLogic)
    const { quota } = useValues(visionQuotaLogic)
    const { disabledReason: quotaDisabledReason, tooltip: quotaTooltip } = quotaUx(quota)

    const submenuItems: LemonMenuItem[] = scannersLoading
        ? [{ label: 'Loading scanners…', disabledReason: 'Loading' }]
        : scanners.length === 0
          ? [
                {
                    label: 'No scanners yet — create one',
                    onClick: () => router.actions.push(urls.replayVision()),
                    'data-attr': 'vision-bulk-scan-create-scanner',
                },
            ]
          : scanners.map((scanner) => ({
                label: scanner.name,
                onClick: () => scanRecordings(scanner.id, selectedRecordingsIds),
                'data-attr': 'vision-bulk-scan-scanner-item',
            }))

    return (
        <LemonMenu
            items={submenuItems}
            placement="right-start"
            trigger="hover"
            buttonSize="xsmall"
            closeOnClickInside
            closeParentPopoverOnClickInside
        >
            <LemonButton
                fullWidth
                role="menuitem"
                size="xsmall"
                icon={<IconEye />}
                sideIcon={<IconChevronRight />}
                disabledReason={
                    scanning
                        ? 'Starting scans…'
                        : selectedRecordingsIds.length === 0
                          ? 'Select recordings to scan'
                          : quotaDisabledReason
                }
                tooltip={quotaTooltip}
                data-attr="vision-bulk-scan-recordings"
            >
                Scan these recordings
            </LemonButton>
        </LemonMenu>
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
    const {
        selectedRecordingsIds,
        otherRecordings,
        visiblePinnedRecordings: pinnedRecordings,
    } = useValues(sessionRecordingsPlaylistLogic)
    const {
        handleBulkDeleteFromPlaylist,
        handleSelectUnselectAll,
        setIsDeleteSelectedRecordingsDialogOpen,
        setIsAddToCollectionModalOpen,
        handleBulkMarkAsViewed,
        handleBulkMarkAsNotViewed,
    } = useActions(sessionRecordingsPlaylistLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    const recordings = type === 'filters' ? otherRecordings : pinnedRecordings
    const checked = recordings.length > 0 && selectedRecordingsIds.length === recordings.length

    const accessControlDisabledReason = getAccessControlDisabledReason(
        AccessControlResourceType.SessionRecording,
        AccessControlLevel.Editor
    )

    const visionEnabled = !!featureFlags[FEATURE_FLAGS.REPLAY_VISION]

    const getActionsMenuItems = (): LemonMenuItem[] => {
        const menuItems: LemonMenuItem[] = [
            {
                label: 'Add to collection...',
                onClick: () => setIsAddToCollectionModalOpen(true),
                'data-attr': 'add-to-collection',
                disabledReason: accessControlDisabledReason,
            },
        ]

        if (type === 'collection' && shortId) {
            menuItems.push({
                label: 'Remove from this collection',
                onClick: () => handleBulkDeleteFromPlaylist(shortId),
                'data-attr': 'remove-from-collection',
                disabledReason: accessControlDisabledReason,
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

        if (visionEnabled) {
            // Custom item so the scanner list opens on hover (the nested `items` API is click-only).
            menuItems.push({
                key: 'bulk-scan-recordings',
                label: () => <BulkScanMenuItem />,
                custom: true,
            })
        }

        menuItems.push({
            label: 'Delete',
            onClick: () => setIsDeleteSelectedRecordingsDialogOpen(true),
            icon: <IconTrash />,
            'data-attr': 'delete-recordings',
            status: 'danger' as const,
            disabledReason: accessControlDisabledReason,
        })

        return menuItems
    }

    return (
        <SettingsBar border="none" className="justify-between">
            <div className="flex items-center">
                <LemonCheckbox
                    disabledReason={
                        recordings.length === 0
                            ? 'No recordings'
                            : recordings.length > MAX_SELECTED_RECORDINGS
                              ? `Cannot select more than ${MAX_SELECTED_RECORDINGS} recordings at once`
                              : undefined
                    }
                    checked={checked}
                    onChange={(checked) => handleSelectUnselectAll(checked, type)}
                    stopPropagation
                    className="ml-2"
                    data-attr="select-all-recordings"
                    aria-label="Select all recordings"
                />
                {filters && setFilters ? (
                    <span className="text-xs font-normal inline-flex items-center ml-2">
                        Sort by:{' '}
                        <SortedBy
                            filters={filters}
                            setFilters={setFilters}
                            disabledReason={recordings.length === 0 ? 'No recordings' : undefined}
                        />
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
                    disabledReason={recordings.length === 0 ? 'No recordings' : undefined}
                />
            </div>
            <ConfirmDeleteRecordings shortId={shortId} />
            <AddToCollectionModal shortId={shortId} />
        </SettingsBar>
    )
}
