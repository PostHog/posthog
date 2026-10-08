import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import posthog from 'posthog-js'

import {
    IconCheck,
    IconChevronRight,
    IconEllipsis,
    IconEye,
    IconInfo,
    IconPlus,
    IconSort,
    IconTrash,
} from '@posthog/icons'
import { LemonBadge, LemonButton, LemonCheckbox, LemonInput, LemonModal, Spinner, Tooltip } from '@posthog/lemon-ui'

import { SettingsBar, SettingsMenu } from 'lib/components/PanelSettings/PanelSettings'
import { dayjs } from 'lib/dayjs'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { IconBlank } from 'lib/lemon-ui/icons'
import { LemonMenu, LemonMenuItem, LemonMenuItems } from 'lib/lemon-ui/LemonMenu/LemonMenu'
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'
import { matchesConfirmationText } from 'lib/utils/confirmationText'
import { sessionRecordingCollectionsLogic } from 'scenes/session-recordings/collections/sessionRecordingCollectionsLogic'
import { urls } from 'scenes/urls'

import { AccessControlLevel, AccessControlResourceType, RecordingUniversalFilters } from '~/types'

import { bulkScanLogic } from 'products/replay_vision/frontend/logics/bulkScanLogic'
import { visionQuotaLogic } from 'products/replay_vision/frontend/logics/visionQuotaLogic'
import { quotaUx } from 'products/replay_vision/frontend/utils/quotaProjection'

import { useAutoplayMenuItems, useHideRecordingsMenuItems, useTimestampFormatMenuItems } from './listViewMenuItems'
import {
    DELETE_CONFIRMATION_TEXT,
    MAX_SELECTED_RECORDINGS,
    RecordingSort,
    preferredRecordingsSortStorage,
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

export function getRecommendedFilterChange(enabled: boolean): Partial<RecordingUniversalFilters> {
    return { recommended_only: enabled }
}

function useSortMenuItems(
    filters: RecordingUniversalFilters,
    setFilters: (filters: Partial<RecordingUniversalFilters>) => void
): LemonMenuItem[] {
    const { canSortByRelevance: showRelevanceSort, listSort } = useValues(sessionRecordingsPlaylistLogic)
    filters = { ...filters, ...listSort }

    const changeSort = (sort: RecordingSort): void => {
        const sortChangedEvent = getSortChangedEvent(filters, sort)
        if (sortChangedEvent) {
            posthog.capture('session recording list sort changed', sortChangedEvent)
        }
        preferredRecordingsSortStorage.set(sort)
        setFilters(sort)
    }

    return [
        ...(showRelevanceSort
            ? [
                  {
                      label: SortingKeyToLabel['surfacing_score'],
                      tooltip: RELEVANCE_SORT_EXPLANATION,
                      onClick: () => changeSort({ order: 'surfacing_score', order_direction: 'DESC' }),
                      'data-attr': 'list-sort-surfacing-score',
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
                    'data-attr': 'list-sort-latest',
                    active: !filters.order || (filters.order === 'start_time' && filters.order_direction !== 'ASC'),
                },
                {
                    label: 'Oldest',
                    onClick: () => changeSort({ order: 'start_time', order_direction: 'ASC' }),
                    'data-attr': 'list-sort-oldest',
                    active: filters.order === 'start_time' && filters.order_direction === 'ASC',
                },
            ],
        },
        {
            label: SortingKeyToLabel['activity_score'],
            onClick: () => changeSort({ order: 'activity_score', order_direction: 'DESC' }),
            'data-attr': 'list-sort-activity',
            active: filters.order === 'activity_score',
        },
        {
            label: SortingKeyToLabel['console_error_count'],
            onClick: () => changeSort({ order: 'console_error_count', order_direction: 'DESC' }),
            'data-attr': 'list-sort-console-errors',
            active: filters.order === 'console_error_count',
        },
        {
            label: 'Longest',
            items: [
                {
                    label: SortingKeyToLabel['duration'],
                    onClick: () => changeSort({ order: 'duration', order_direction: 'DESC' }),
                    'data-attr': 'list-sort-duration',
                    active: filters.order === 'duration',
                },
                {
                    label: SortingKeyToLabel['active_seconds'],
                    onClick: () => changeSort({ order: 'active_seconds', order_direction: 'DESC' }),
                    'data-attr': 'list-sort-active-seconds',
                    active: filters.order === 'active_seconds',
                },
                {
                    label: SortingKeyToLabel['inactive_seconds'],
                    onClick: () => changeSort({ order: 'inactive_seconds', order_direction: 'DESC' }),
                    'data-attr': 'list-sort-inactive-seconds',
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
                    'data-attr': 'list-sort-clicks',
                    active: filters.order === 'click_count',
                },
                {
                    label: SortingKeyToLabel['keypress_count'],
                    onClick: () => changeSort({ order: 'keypress_count', order_direction: 'DESC' }),
                    'data-attr': 'list-sort-keypresses',
                    active: filters.order === 'keypress_count',
                },
                {
                    label: SortingKeyToLabel['mouse_activity_count'],
                    onClick: () => changeSort({ order: 'mouse_activity_count', order_direction: 'DESC' }),
                    'data-attr': 'list-sort-mouse-activity',
                    active: filters.order === 'mouse_activity_count',
                },
            ],
        },
        {
            label: 'Expiration',
            onClick: () => changeSort({ order: 'recording_ttl', order_direction: 'ASC' }),
            'data-attr': 'list-sort-expiration',
            active: filters.order === 'recording_ttl',
        },
    ]
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
    const { listSort } = useValues(sessionRecordingsPlaylistLogic)
    const items = useSortMenuItems(filters, setFilters)
    filters = { ...filters, ...listSort }

    return (
        <SettingsMenu
            data-attr="list-sort-menu"
            highlightWhenActive={false}
            disabledReason={disabledReason}
            items={items}
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

function useRecommendedOnlyToggle(
    filters: RecordingUniversalFilters,
    setFilters: (filters: Partial<RecordingUniversalFilters>) => void
): { enabled: boolean; checked: boolean; toggle: (checked: boolean) => void } {
    const { canFilterByRelevance: enabled } = useValues(sessionRecordingsPlaylistLogic)
    const checked = !!filters.recommended_only
    const toggle = (checked: boolean): void => {
        posthog.capture('session recording recommended filter changed', { enabled: checked })
        setFilters(getRecommendedFilterChange(checked))
    }
    return { enabled, checked, toggle }
}

function useRecommendedOnlyMenuItem(
    filters: RecordingUniversalFilters,
    setFilters: (filters: Partial<RecordingUniversalFilters>) => void
): LemonMenuItem | null {
    const { enabled, checked, toggle } = useRecommendedOnlyToggle(filters, setFilters)
    if (!enabled) {
        return null
    }
    return {
        label: 'High relevance only',
        icon: checked ? <IconCheck /> : <IconBlank />,
        active: checked,
        onClick: () => toggle(!checked),
        'data-attr': 'session-recordings-recommended-only',
    }
}

function ListViewMenu({
    filters,
    setFilters,
    disabledReason,
}: {
    filters: RecordingUniversalFilters
    setFilters: (filters: Partial<RecordingUniversalFilters>) => void
    disabledReason?: string
}): JSX.Element {
    const sortItems = useSortMenuItems(filters, setFilters)
    const recommendedItem = useRecommendedOnlyMenuItem(filters, setFilters)
    const hideItems = useHideRecordingsMenuItems()
    const timestampItems = useTimestampFormatMenuItems()

    const items: LemonMenuItems = [
        { title: 'Sort by', items: sortItems },
        { title: 'Show', items: [recommendedItem, ...hideItems] },
        { title: 'Timestamps', items: timestampItems },
    ]

    return (
        <LemonMenu items={items} buttonSize="xsmall" closeOnClickInside={false} placement="bottom-end">
            <LemonButton
                size="xsmall"
                icon={<IconSort className="text-lg" />}
                disabledReason={disabledReason}
                data-attr="list-view-menu"
            >
                View
            </LemonButton>
        </LemonMenu>
    )
}

function RecommendedOnlyFilter({
    filters,
    setFilters,
}: {
    filters: RecordingUniversalFilters
    setFilters: (filters: Partial<RecordingUniversalFilters>) => void
}): JSX.Element | null {
    const { enabled, checked, toggle } = useRecommendedOnlyToggle(filters, setFilters)
    if (!enabled) {
        return null
    }

    return (
        <Tooltip title="Show recordings with high relevance">
            <span className="inline-flex items-center ml-3">
                <LemonCheckbox
                    label="High relevance"
                    checked={checked}
                    onChange={toggle}
                    data-attr="session-recordings-recommended-only"
                />
            </span>
        </Tooltip>
    )
}

function ConfirmDeleteRecordings({ shortId }: { shortId?: string }): JSX.Element {
    const {
        selectedRecordingsIds,
        isDeleteSelectedRecordingsDialogOpen,
        deleteConfirmationText,
        isDeletingSelectedRecordings,
    } = useValues(sessionRecordingsPlaylistLogic)
    const { setIsDeleteSelectedRecordingsDialogOpen, setDeleteConfirmationText, handleDeleteSelectedRecordings } =
        useActions(sessionRecordingsPlaylistLogic)

    const isConfirmationValid = matchesConfirmationText(deleteConfirmationText, DELETE_CONFIRMATION_TEXT)

    const handleClose = (): void => {
        if (isDeletingSelectedRecordings) {
            return
        }
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
                        disabled={isDeletingSelectedRecordings}
                        autoFocus
                    />
                    {deleteConfirmationText.length > 0 && !isConfirmationValid && (
                        <p className="text-danger text-sm mb-0">
                            That doesn't match. Please type "{DELETE_CONFIRMATION_TEXT}" to confirm.
                        </p>
                    )}
                </div>
                <div className="bg-warning-highlight border border-warning rounded p-2 text-sm">
                    This action cannot be undone. Deleting recordings doesn't affect your billing.
                </div>
            </div>
            <div className="flex justify-end gap-2 mt-4">
                <LemonButton
                    data-attr="list-delete-modal-cancel"
                    type="secondary"
                    onClick={handleClose}
                    disabledReason={isDeletingSelectedRecordings ? 'Deleting...' : undefined}
                >
                    Cancel
                </LemonButton>
                <LemonButton
                    data-attr="list-delete-selected-confirm"
                    type="primary"
                    status="danger"
                    loading={isDeletingSelectedRecordings}
                    disabledReason={!isConfirmationValid ? 'Please type the correct confirmation text' : undefined}
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
                        <LemonButton
                            data-attr="list-add-to-collection-modal-cancel"
                            type="secondary"
                            onClick={handleClose}
                        >
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
                        <LemonButton
                            data-attr="list-new-collection-cancel"
                            type="secondary"
                            onClick={() => setIsCreatingNewCollectionInModal(false)}
                        >
                            Back
                        </LemonButton>
                        <LemonButton
                            data-attr="list-new-collection-create"
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
    const autoplayItems = useAutoplayMenuItems()
    const consolidatedControls = useFeatureFlag('REPLAY_CONSOLIDATED_CONTROLS')
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

    const recordings = type === 'filters' ? otherRecordings : pinnedRecordings
    const checked = recordings.length > 0 && selectedRecordingsIds.length === recordings.length

    const accessControlDisabledReason = getAccessControlDisabledReason(
        AccessControlResourceType.SessionRecording,
        AccessControlLevel.Editor
    )

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

        // Custom item so the scanner list opens on hover (the nested `items` API is click-only).
        menuItems.push({
            key: 'bulk-scan-recordings',
            label: () => <BulkScanMenuItem />,
            custom: true,
        })

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

    const selectAllDisabledReason =
        recordings.length === 0
            ? 'No recordings'
            : recordings.length > MAX_SELECTED_RECORDINGS
              ? `Cannot select more than ${MAX_SELECTED_RECORDINGS} recordings at once`
              : undefined

    return (
        <SettingsBar border="none" className="justify-between">
            <div className="flex items-center">
                <Tooltip title={selectAllDisabledReason ? undefined : 'Select all recordings'}>
                    <span className={clsx('flex', consolidatedControls ? 'ml-[7px]' : 'ml-2')}>
                        <LemonCheckbox
                            disabledReason={selectAllDisabledReason}
                            checked={checked}
                            onChange={(checked) => handleSelectUnselectAll(checked, type)}
                            stopPropagation
                            data-attr="select-all-recordings"
                            aria-label="Select all recordings"
                        />
                    </span>
                </Tooltip>
                {filters && setFilters && !consolidatedControls ? (
                    <>
                        <span className="text-xs font-normal inline-flex items-center ml-2">
                            Sort by:{' '}
                            <SortedBy
                                filters={filters}
                                setFilters={setFilters}
                                disabledReason={recordings.length === 0 ? 'No recordings' : undefined}
                            />
                        </span>
                        <RecommendedOnlyFilter filters={filters} setFilters={setFilters} />
                    </>
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
                {consolidatedControls && filters && setFilters && (
                    <ListViewMenu
                        filters={filters}
                        setFilters={setFilters}
                        disabledReason={recordings.length === 0 ? 'No recordings' : undefined}
                    />
                )}
                <SettingsMenu
                    data-attr="list-autoplay-menu"
                    items={[{ label: 'Autoplay', items: autoplayItems }]}
                    icon={<IconEllipsis className="rotate-90" />}
                    placement={consolidatedControls ? 'bottom-end' : undefined}
                    disabledReason={recordings.length === 0 ? 'No recordings' : undefined}
                />
            </div>
            <ConfirmDeleteRecordings shortId={shortId} />
            <AddToCollectionModal shortId={shortId} />
        </SettingsBar>
    )
}
