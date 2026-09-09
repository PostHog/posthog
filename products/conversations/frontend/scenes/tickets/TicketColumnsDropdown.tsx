import { useActions, useValues } from 'kea'

import { IconTuning } from 'lib/lemon-ui/icons'
import {
    Button,
    DropdownMenu,
    DropdownMenuCheckboxItem,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
} from 'lib/ui/quill'

import { isTicketColumnMandatory, offerableTicketColumns, ticketColumnLabel } from './ticketColumns'
import { ticketColumnsLogic } from './ticketColumnsLogic'

interface TicketColumnsDropdownProps {
    aiEnabled: boolean
    embedded?: boolean
}

export function TicketColumnsDropdown({ aiEnabled, embedded = false }: TicketColumnsDropdownProps): JSX.Element {
    const { visibleColumns } = useValues(ticketColumnsLogic)
    const { toggleColumn, setVisibleColumns } = useActions(ticketColumnsLogic)

    const offerable = offerableTicketColumns({ aiEnabled, embedded })
    const shownCount = offerable.filter((key) => visibleColumns.includes(key) || isTicketColumnMandatory(key)).length
    const allShown = shownCount === offerable.length
    const tooltip = allShown ? 'Show all columns' : `Show ${shownCount} of ${offerable.length} columns`

    return (
        <DropdownMenu>
            <DropdownMenuTrigger
                render={
                    <Button
                        variant="default"
                        size="icon-sm"
                        data-attr="support-tickets-column-selector"
                        aria-label={tooltip}
                        title={tooltip}
                    >
                        <IconTuning />
                    </Button>
                }
            />
            <DropdownMenuContent align="end" className="min-w-48">
                {offerable.map((key) => {
                    const mandatory = isTicketColumnMandatory(key)
                    return (
                        <DropdownMenuCheckboxItem
                            key={key}
                            checked={mandatory || visibleColumns.includes(key)}
                            disabled={mandatory}
                            closeOnClick={false}
                            title={mandatory ? 'This column identifies the ticket' : undefined}
                            onCheckedChange={() => toggleColumn(key)}
                        >
                            {ticketColumnLabel(key)}
                        </DropdownMenuCheckboxItem>
                    )
                })}
                <DropdownMenuSeparator />
                <DropdownMenuItem
                    disabled={allShown}
                    title={allShown ? 'Every column is already shown' : undefined}
                    onClick={() => setVisibleColumns(offerable)}
                >
                    Show all columns
                </DropdownMenuItem>
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
