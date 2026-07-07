import { useActions, useValues } from 'kea'

import { IconArchive, IconX } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { inboxBulkActionsLogic } from '../../logics/inboxBulkActionsLogic'
import { openDismissReportDialog } from './DismissReportDialog'

/**
 * Bulk action toolbar shown when one or more reports are multi-selected.
 * Mirrors desktop `InboxBulkSelectionBar` (the dismiss + clear slice). Selection
 * and the bulk-dismiss call live in `inboxBulkActionsLogic`; delete / reingest
 * remain on `inboxSceneLogic` per-report.
 */
export function InboxBulkSelectionBar(): JSX.Element | null {
    const { selectedCount, isDismissing } = useValues(inboxBulkActionsLogic)
    const { clearSelection, bulkDismiss } = useActions(inboxBulkActionsLogic)

    if (selectedCount === 0) {
        return null
    }

    return (
        <div className="flex items-center justify-between gap-3 flex-wrap rounded border border-accent bg-accent-highlight-secondary px-3 py-2">
            <div className="flex items-center gap-2 min-w-0">
                <span className="font-medium text-sm shrink-0">{selectedCount} selected</span>
                <span className="text-xs text-muted">Shift-click range · ⌘-click toggle · Esc to clear</span>
            </div>

            <div className="flex items-center gap-2 flex-wrap">
                <LemonButton
                    type="secondary"
                    size="small"
                    icon={<IconArchive />}
                    loading={isDismissing}
                    disabledReason={isDismissing ? 'Archiving…' : undefined}
                    onClick={() =>
                        openDismissReportDialog({
                            selectedCount,
                            onConfirm: ({ reason, note }) => bulkDismiss(reason, note),
                        })
                    }
                >
                    Archive
                </LemonButton>
                <LemonButton
                    type="tertiary"
                    size="small"
                    icon={<IconX />}
                    tooltip="Clear selection"
                    aria-label="Clear selection"
                    onClick={clearSelection}
                />
            </div>
        </div>
    )
}
