import { useActions, useValues } from 'kea'

import { IconEllipsis } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { LemonMenu, LemonMenuItem, LemonMenuItemLeafCallback } from 'lib/lemon-ui/LemonMenu/LemonMenu'
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

    const primaryItems: LemonMenuItemLeafCallback[] = [
        {
            label: 'Add to collection',
            onClick: () => setIsAddToCollectionModalOpen(true),
            disabledReason: accessControlDisabledReason,
            'data-attr': 'add-to-collection',
        },
        { label: 'Mark watched', onClick: () => handleBulkMarkAsViewed(shortId), 'data-attr': 'mark-as-viewed' },
        {
            label: 'Delete',
            status: 'danger',
            onClick: () => setIsDeleteSelectedRecordingsDialogOpen(true),
            disabledReason: accessControlDisabledReason,
            'data-attr': 'delete-recordings',
        },
    ]

    return (
        <div className="flex flex-1 min-w-0 items-center gap-1 text-xs" data-attr="list-bulk-bar">
            <span className="font-semibold px-1 shrink-0">{selectedRecordingsIds.length} selected</span>
            <div className="hidden @min-[24rem]/list-header:flex items-center gap-1">
                {primaryItems.map((item) => (
                    <LemonButton
                        key={item['data-attr']}
                        size="xsmall"
                        status={item.status}
                        onClick={item.onClick}
                        disabledReason={item.disabledReason}
                        data-attr={item['data-attr']}
                    >
                        {item.label}
                    </LemonButton>
                ))}
                <LemonMenu items={moreItems} placement="bottom-end" buttonSize="xsmall">
                    <LemonButton
                        size="xsmall"
                        icon={<IconEllipsis />}
                        aria-label="More actions"
                        data-attr="bulk-action-menu"
                    />
                </LemonMenu>
            </div>
            <div className="@min-[24rem]/list-header:hidden">
                <LemonMenu items={[...primaryItems, ...moreItems]} placement="bottom-end" buttonSize="xsmall">
                    <LemonButton
                        size="xsmall"
                        icon={<IconEllipsis />}
                        aria-label="Bulk actions"
                        data-attr="bulk-action-menu-narrow"
                    />
                </LemonMenu>
            </div>
            <ConfirmDeleteRecordings shortId={shortId} />
            <AddToCollectionModal shortId={shortId} />
        </div>
    )
}
