import { useActions, useMountedLogic, useValues } from 'kea'

import { IconX } from '@posthog/icons'
import { LemonButton, LemonSelect } from '@posthog/lemon-ui'

import { BulkUpdateTagsButton } from 'lib/components/BulkActions/BulkUpdateTagsButton'
import { pluralize } from 'lib/utils/strings'

import { type TicketStatus, statusOptionsWithoutAll } from '../../types'
import { supportTicketsSceneLogic } from './supportTicketsSceneLogic'

export function TicketSelectionBar(): JSX.Element {
    const logic = useMountedLogic(supportTicketsSceneLogic)
    const { selectedTicketIds, selectedTickets, editableSelectedTicketIds, bulkUpdating } = useValues(logic)
    const { bulkUpdateStatus, clearSelectedTickets, loadTickets } = useActions(logic)

    const editableTicketIds = editableSelectedTicketIds
    const skippedCount = selectedTicketIds.length - editableTicketIds.length
    const noEditableSelectionReason =
        editableTicketIds.length === 0 ? "You don't have edit access to any of the selected tickets" : undefined
    const restrictedSelectionTooltip =
        skippedCount > 0 && editableTicketIds.length > 0
            ? `${skippedCount} selected ticket(s) will be skipped because you don't have edit access to them`
            : undefined
    const selectedStatuses = selectedTickets.map((t) => t.status)
    const currentStatus = selectedStatuses.reduce<TicketStatus | 'mixed' | null>((acc, s) => {
        if (acc === null) {
            return s
        }
        return acc === s ? acc : 'mixed'
    }, null)

    return (
        <div className="flex flex-wrap items-center gap-2 rounded border border-primary bg-surface-secondary px-2 py-1">
            <span className="text-sm font-semibold">{pluralize(selectedTicketIds.length, 'ticket')} selected</span>
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
                type="tertiary"
                size="small"
                icon={<IconX />}
                onClick={clearSelectedTickets}
                disabledReason={bulkUpdating ? 'Updating…' : undefined}
                className="ml-auto"
                data-attr="clear-ticket-selection"
            >
                Clear selection
            </LemonButton>
        </div>
    )
}
