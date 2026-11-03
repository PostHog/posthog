import { useActions, useValues } from 'kea'

import { IconEllipsis, IconEye } from '@posthog/icons'
import { Button, DropdownMenu, DropdownMenuContent, DropdownMenuTrigger } from '@posthog/quill'

import { LemonMenuItem, LemonMenuItemLeafCallback } from 'lib/lemon-ui/LemonMenu/LemonMenu'
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { QuillMenuItems } from './QuillMenuItems'
import { sessionRecordingsPlaylistLogic } from './sessionRecordingsPlaylistLogic'
import { AddToCollectionModal, ConfirmDeleteRecordings } from './SessionRecordingsPlaylistSettings'
import { useBulkScanMenuItems } from './useBulkScanMenuItems'

export function ReplayBulkBar({ type, shortId }: { type: 'filters' | 'collection'; shortId?: string }): JSX.Element {
    const { selectedRecordingsIds } = useValues(sessionRecordingsPlaylistLogic)
    const {
        setIsAddToCollectionModalOpen,
        setIsDeleteSelectedRecordingsDialogOpen,
        handleBulkMarkAsViewed,
        handleBulkMarkAsNotViewed,
        handleBulkDeleteFromPlaylist,
    } = useActions(sessionRecordingsPlaylistLogic)
    const bulkScan = useBulkScanMenuItems()
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
        {
            label: 'Scan these recordings',
            icon: <IconEye />,
            items: bulkScan.items,
            disabledReason: bulkScan.disabledReason,
            tooltip: bulkScan.tooltip,
            'data-attr': 'vision-bulk-scan-recordings',
        },
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
                    <Button
                        key={item['data-attr']}
                        variant={item.status === 'danger' ? 'destructive-outline' : 'default'}
                        onClick={item.onClick}
                        disabledReason={item.disabledReason}
                        data-attr={item['data-attr']}
                    >
                        {item.label}
                    </Button>
                ))}
                <DropdownMenu>
                    <DropdownMenuTrigger
                        render={<Button size="icon" aria-label="More actions" data-attr="bulk-action-menu" />}
                    >
                        <IconEllipsis />
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end">
                        <QuillMenuItems items={moreItems} />
                    </DropdownMenuContent>
                </DropdownMenu>
            </div>
            <div className="@min-[24rem]/list-header:hidden">
                <DropdownMenu>
                    <DropdownMenuTrigger
                        render={<Button size="icon" aria-label="Bulk actions" data-attr="bulk-action-menu-narrow" />}
                    >
                        <IconEllipsis />
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end">
                        <QuillMenuItems items={[...primaryItems, ...moreItems]} />
                    </DropdownMenuContent>
                </DropdownMenu>
            </div>
            <ConfirmDeleteRecordings shortId={shortId} />
            <AddToCollectionModal shortId={shortId} />
        </div>
    )
}
