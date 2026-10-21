import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { IconEllipsis, IconX } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { LemonMenu, LemonMenuItem } from 'lib/lemon-ui/LemonMenu/LemonMenu'
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { MAX_SELECTED_RECORDINGS, sessionRecordingsPlaylistLogic } from './sessionRecordingsPlaylistLogic'
import { AddToCollectionModal, BulkScanMenuItem, ConfirmDeleteRecordings } from './SessionRecordingsPlaylistSettings'

/** Replaces the filter row while recordings are selected: the count, select all, and the bulk actions. */
export function ReplayBulkBar({ type, shortId }: { type: 'filters' | 'collection'; shortId?: string }): JSX.Element {
    const {
        selectedRecordingsIds,
        otherRecordings,
        visiblePinnedRecordings: pinnedRecordings,
    } = useValues(sessionRecordingsPlaylistLogic)
    const {
        setSelectedRecordingsIds,
        handleSelectUnselectAll,
        setIsAddToCollectionModalOpen,
        setIsDeleteSelectedRecordingsDialogOpen,
        handleBulkMarkAsViewed,
        handleBulkMarkAsNotViewed,
        handleBulkDeleteFromPlaylist,
    } = useActions(sessionRecordingsPlaylistLogic)
    const recordings = type === 'filters' ? otherRecordings : pinnedRecordings
    const allSelected = recordings.length > 0 && selectedRecordingsIds.length === recordings.length
    const accessControlDisabledReason = getAccessControlDisabledReason(
        AccessControlResourceType.SessionRecording,
        AccessControlLevel.Editor
    )
    const clear = (): void => setSelectedRecordingsIds([])

    useEffect(() => {
        const onKeyDown = (event: KeyboardEvent): void => {
            if (event.key === 'Escape') {
                clear()
            }
        }
        document.addEventListener('keydown', onKeyDown)
        return () => document.removeEventListener('keydown', onKeyDown)
    }, [clear])

    const moreItems: LemonMenuItem[] = [
        {
            label: 'Mark as not viewed',
            onClick: () => handleBulkMarkAsNotViewed(shortId),
            'data-attr': 'mark-as-not-viewed',
        },
        ...(type === 'collection' && shortId
            ? [
                  {
                      label: 'Remove from this collection',
                      onClick: () => handleBulkDeleteFromPlaylist(shortId),
                      'data-attr': 'remove-from-collection',
                      disabledReason: accessControlDisabledReason,
                  },
              ]
            : []),
        { key: 'bulk-scan-recordings', label: () => <BulkScanMenuItem />, custom: true },
    ]

    return (
        <div className="flex items-center gap-1 flex-wrap text-xs" data-attr="list-bulk-bar">
            <span className="font-semibold px-1">{selectedRecordingsIds.length} selected</span>
            <LemonButton
                size="xsmall"
                onClick={() => handleSelectUnselectAll(!allSelected, type)}
                disabledReason={
                    recordings.length > MAX_SELECTED_RECORDINGS
                        ? `Cannot select more than ${MAX_SELECTED_RECORDINGS} recordings at once`
                        : undefined
                }
                data-attr="select-all-recordings"
            >
                {allSelected ? 'Clear selection' : `Select all ${recordings.length}`}
            </LemonButton>
            <LemonButton
                size="xsmall"
                onClick={() => setIsAddToCollectionModalOpen(true)}
                disabledReason={accessControlDisabledReason}
                data-attr="add-to-collection"
            >
                Add to collection
            </LemonButton>
            <LemonButton size="xsmall" onClick={() => handleBulkMarkAsViewed(shortId)} data-attr="mark-as-viewed">
                Mark watched
            </LemonButton>
            <LemonButton
                size="xsmall"
                status="danger"
                onClick={() => setIsDeleteSelectedRecordingsDialogOpen(true)}
                disabledReason={accessControlDisabledReason}
                data-attr="delete-recordings"
            >
                Delete
            </LemonButton>
            <LemonMenu items={moreItems} placement="bottom-end" buttonSize="xsmall">
                <LemonButton
                    size="xsmall"
                    icon={<IconEllipsis />}
                    aria-label="More actions"
                    data-attr="bulk-action-menu"
                />
            </LemonMenu>
            <LemonButton
                size="xsmall"
                icon={<IconX />}
                className="ml-auto"
                onClick={clear}
                tooltip="Clear selection (Esc)"
                aria-label="Clear selection"
                data-attr="list-bulk-clear"
            />
            <ConfirmDeleteRecordings shortId={shortId} />
            <AddToCollectionModal shortId={shortId} />
        </div>
    )
}
