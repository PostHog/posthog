import { useActions, useValues } from 'kea'

import { LemonSelect } from '@posthog/lemon-ui'

import { BulkUpdateTagsButton } from 'lib/components/BulkActions/BulkUpdateTagsButton'

import { supportTicketsSceneLogic } from '../../scenes/tickets/supportTicketsSceneLogic'
import { type TicketStatus, statusOptionsWithoutAll } from '../../types'

export function TicketListBulkActions(): JSX.Element {
    const { editableSelectedTicketIds, bulkActionState, bulkUpdating } = useValues(supportTicketsSceneLogic)
    const { markSelectedTicketsAs, clearSelectedTickets, loadTickets } = useActions(supportTicketsSceneLogic)
    const { noEditableSelectionReason, restrictedSelectionTooltip } = bulkActionState

    return (
        <div className="flex flex-wrap items-center gap-2">
            <LemonSelect
                onChange={(value) => {
                    if (value) {
                        markSelectedTicketsAs(value as TicketStatus)
                    }
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
                selectedIds={editableSelectedTicketIds}
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
