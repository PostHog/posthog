import { useActions, useValues } from 'kea'

import { IconEllipsis } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { LemonMenu, LemonMenuItem } from 'lib/lemon-ui/LemonMenu/LemonMenu'
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { sessionRecordingsPlaylistLogic } from './sessionRecordingsPlaylistLogic'
import { AddToCollectionModal, BulkScanMenuItem, ConfirmDeleteRecordings } from './SessionRecordingsPlaylistSettings'

export function ReplayBulkBar({ type, shortId }: { type: 'filters' | 'collection'; shortId?: string }): JSX.Element {
    const { selectedRecordingsIds } = useValues(sessionRecordingsPlaylistLogic)
    const {
        setIsAddToCollectionModalOpen,
        setIsDeleteSelectedRecordingsDialogOpen,
        handleBulkMarkAsViewed,
        handleBulkMarkAsNotViewed,
        handleBulkDeleteFromPlaylist,
    } = useActions(sessionRecordingsPlaylistLogic)
    const accessControlDisabledReason = getAccessControlDisabledReason(
        AccessControlResourceType.SessionRecording,
        AccessControlLevel.Editor
    )
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
        <div className="flex flex-1 items-center gap-1 flex-wrap text-xs" data-attr="list-bulk-bar">
            <span className="font-semibold px-1">{selectedRecordingsIds.length} selected</span>
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
            <ConfirmDeleteRecordings shortId={shortId} />
            <AddToCollectionModal shortId={shortId} />
        </div>
    )
}
