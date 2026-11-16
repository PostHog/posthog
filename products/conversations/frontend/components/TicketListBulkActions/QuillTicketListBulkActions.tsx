import { useActions, useValues } from 'kea'

import { IconChevronDown, IconX } from '@posthog/icons'
import {
    Button,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuRadioGroup,
    DropdownMenuRadioItem,
    DropdownMenuTrigger,
    Text,
} from '@posthog/quill'

import { QuillBulkUpdateTagsButton } from 'lib/components/BulkActions/QuillBulkUpdateTagsButton'

import { supportTicketsSceneLogic } from '../../scenes/tickets/supportTicketsSceneLogic'
import { type TicketStatus, statusOptionsWithoutAll } from '../../types'

/** The bulk actions, on a bar that shows only while tickets are selected. */
export function QuillTicketListBulkActions(): JSX.Element | null {
    const { selectedTicketIds, editableSelectedTicketIds, bulkActionState, bulkUpdating } =
        useValues(supportTicketsSceneLogic)
    const { markSelectedTicketsAs, clearSelectedTickets, loadTickets } = useActions(supportTicketsSceneLogic)
    const { currentStatus, noEditableSelectionReason, restrictedSelectionTooltip } = bulkActionState

    if (selectedTicketIds.length === 0) {
        return null
    }

    return (
        // Sticky at the bottom of the scene, after the table, so it never pushes the rows down when it shows.
        <div className="sticky bottom-4 z-10 flex justify-center">
            <div
                data-quill-inverted
                role="toolbar"
                aria-label="Bulk actions"
                className="flex max-w-full flex-wrap items-center gap-2 rounded-lg bg-background px-3 py-2 text-foreground shadow-md"
            >
                <Text size="xs" weight="medium" render={<span />} className="whitespace-nowrap">
                    {`${selectedTicketIds.length} selected`}
                </Text>
                <DropdownMenu>
                    <DropdownMenuTrigger
                        render={
                            <Button
                                variant="outline"
                                loading={bulkUpdating}
                                disabledReason={noEditableSelectionReason}
                                tooltip={restrictedSelectionTooltip}
                                data-attr="tickets-bulk-mark-as"
                            />
                        }
                    >
                        Mark as
                        <IconChevronDown />
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="start">
                        <DropdownMenuRadioGroup
                            value={currentStatus === 'mixed' ? null : currentStatus}
                            onValueChange={(status: TicketStatus) => markSelectedTicketsAs(status)}
                        >
                            {statusOptionsWithoutAll.map((option) => (
                                <DropdownMenuRadioItem key={option.value} value={option.value}>
                                    {option.label}
                                </DropdownMenuRadioItem>
                            ))}
                        </DropdownMenuRadioGroup>
                    </DropdownMenuContent>
                </DropdownMenu>
                <QuillBulkUpdateTagsButton
                    resource="conversations/tickets"
                    selectedIds={editableSelectedTicketIds}
                    disabledReason={noEditableSelectionReason}
                    tooltip={restrictedSelectionTooltip}
                    onSuccess={() => {
                        clearSelectedTickets()
                        loadTickets()
                    }}
                />
                <Button
                    size="icon"
                    aria-label="Clear selection"
                    tooltip="Clear selection"
                    onClick={() => clearSelectedTickets()}
                    data-attr="tickets-bulk-clear-selection"
                >
                    <IconX />
                </Button>
            </div>
        </div>
    )
}
