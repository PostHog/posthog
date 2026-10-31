import { useActions, useValues } from 'kea'

import { IconTrash } from '@posthog/icons'
import { LemonButton, LemonSelect } from '@posthog/lemon-ui'

import { BulkUpdateTagsButton } from 'lib/components/BulkActions/BulkUpdateTagsButton'

import { supportTicketsSceneLogic } from '../../scenes/tickets/supportTicketsSceneLogic'
import { type TicketStatus, statusOptionsWithoutAll } from '../../types'

export function TicketListBulkActions(): JSX.Element {
    const { selectedTicketIds, selectedTickets, editableSelectedTicketIds, deletableSelectedTicketIds, bulkUpdating } =
        useValues(supportTicketsSceneLogic)
    const { bulkUpdateStatus, bulkDeleteTickets, clearSelectedTickets, loadTickets } =
        useActions(supportTicketsSceneLogic)

    const hasSelection = selectedTicketIds.length > 0
    const editableTicketIds = editableSelectedTicketIds
    const hasRestrictedSelection = editableTicketIds.length < selectedTicketIds.length
    const selectedStatuses = selectedTickets.map((t) => t.status)
    const currentStatus = selectedStatuses.reduce<TicketStatus | 'mixed' | null>((acc, s) => {
        if (acc === null) {
            return s
        }
        return acc === s ? acc : 'mixed'
    }, null)

    const noEditableSelectionReason = !hasSelection
        ? 'Select tickets first'
        : editableTicketIds.length === 0
          ? "You don't have edit access to any of the selected tickets"
          : undefined
    const restrictedSelectionTooltip =
        hasRestrictedSelection && editableTicketIds.length > 0
            ? `${selectedTicketIds.length - editableTicketIds.length} selected ticket(s) will be skipped because you don't have edit access to them`
            : undefined

    const skippedDeleteCount = selectedTicketIds.length - deletableSelectedTicketIds.length
    const noDeletableSelectionReason = !hasSelection
        ? 'Select tickets first'
        : deletableSelectedTicketIds.length === 0
          ? "You don't have permission to delete the selected tickets"
          : undefined
    const restrictedDeleteTooltip =
        skippedDeleteCount > 0 && deletableSelectedTicketIds.length > 0
            ? `${skippedDeleteCount} selected ticket(s) will be skipped because you don't have permission to delete them`
            : undefined

    return (
        <div className="flex flex-wrap items-center gap-2">
            <LemonSelect
                onChange={(value) => {
                    if (!value || value === currentStatus || editableTicketIds.length === 0) {
                        return
                    }
                    bulkUpdateStatus(editableTicketIds, value as TicketStatus)
                }}
                value={null}
                placeholder="Mark as"
                loading={bulkUpdating}
                disabledReason={bulkUpdating ? 'Updating…' : noEditableSelectionReason}
                tooltip={restrictedSelectionTooltip}
                options={statusOptionsWithoutAll.map((o) => ({ value: o.value, label: o.label }))}
                size="small"
            />
            <BulkUpdateTagsButton
                resource="conversations/tickets"
                selectedIds={editableTicketIds}
                disabledReason={noEditableSelectionReason}
                tooltip={restrictedSelectionTooltip}
                onSuccess={() => {
                    clearSelectedTickets()
                    loadTickets()
                }}
            />
            <LemonButton
                type="secondary"
                status="danger"
                size="small"
                icon={<IconTrash />}
                onClick={() => bulkDeleteTickets(deletableSelectedTicketIds)}
                loading={bulkUpdating}
                disabledReason={bulkUpdating ? 'Updating…' : noDeletableSelectionReason}
                tooltip={restrictedDeleteTooltip}
                data-attr="support-tickets-bulk-delete"
            >
                Delete
            </LemonButton>
        </div>
    )
}
