import { useActions, useValues } from 'kea'

import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue, Spinner } from 'lib/ui/quill'

import { supportTicketsSceneLogic } from '../../scenes/tickets/supportTicketsSceneLogic'
import { type TicketStatus, statusOptionsWithoutAll } from '../../types'
import { TicketBulkUpdateTagsButton } from '../TicketBulkUpdateTagsButton/TicketBulkUpdateTagsButton'

export function TicketListBulkActions(): JSX.Element {
    const { selectedTicketIds, selectedTickets, editableSelectedTicketIds, bulkUpdating } =
        useValues(supportTicketsSceneLogic)
    const { bulkUpdateStatus, clearSelectedTickets, loadTickets } = useActions(supportTicketsSceneLogic)

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
    const disabled = bulkUpdating || !!noEditableSelectionReason
    const triggerTitle = bulkUpdating ? 'Updating…' : (noEditableSelectionReason ?? restrictedSelectionTooltip)

    return (
        <div className="flex flex-wrap items-center gap-2">
            <Select
                value={null}
                disabled={disabled}
                onValueChange={(value: TicketStatus | null) => {
                    if (!value || value === currentStatus || editableTicketIds.length === 0) {
                        return
                    }
                    bulkUpdateStatus(editableTicketIds, value)
                }}
            >
                <SelectTrigger size="sm" title={triggerTitle} aria-busy={bulkUpdating}>
                    {bulkUpdating ? <Spinner /> : null}
                    <SelectValue placeholder="Mark as" />
                </SelectTrigger>
                <SelectContent align="start" alignItemWithTrigger={false}>
                    {statusOptionsWithoutAll.map((option) => (
                        <SelectItem key={option.value} value={option.value}>
                            {option.label}
                        </SelectItem>
                    ))}
                </SelectContent>
            </Select>
            <TicketBulkUpdateTagsButton
                selectedIds={editableTicketIds}
                disabledReason={noEditableSelectionReason}
                tooltip={restrictedSelectionTooltip}
                onSuccess={() => {
                    clearSelectedTickets()
                    loadTickets()
                }}
            />
        </div>
    )
}
