import { useActions, useValues } from 'kea'

import { IconChevronDown } from '@posthog/icons'
import { LemonButton, LemonCheckbox, LemonDivider, LemonDropdown } from '@posthog/lemon-ui'

import { IconTuning } from 'lib/lemon-ui/icons'
import { userLogic } from 'scenes/userLogic'

import { isTicketColumnMandatory, offerableTicketColumns, ticketColumnLabel } from './ticketColumns'
import { ticketColumnsLogic } from './ticketColumnsLogic'

interface TicketColumnsDropdownProps {
    aiEnabled: boolean
    embedded?: boolean
}

export function TicketColumnsDropdown({ aiEnabled, embedded = false }: TicketColumnsDropdownProps): JSX.Element {
    const { visibleColumns } = useValues(ticketColumnsLogic)
    const { toggleColumn, setVisibleColumns } = useActions(ticketColumnsLogic)
    const { user } = useValues(userLogic)

    const offerable = offerableTicketColumns({ aiEnabled, embedded, staff: !!user?.is_staff })
    const shownCount = offerable.filter((key) => visibleColumns.includes(key) || isTicketColumnMandatory(key)).length
    const allShown = shownCount === offerable.length

    return (
        <LemonDropdown
            closeOnClickInside={false}
            overlay={
                <div className="space-y-px p-1 min-w-48">
                    {offerable.map((key) => {
                        const mandatory = isTicketColumnMandatory(key)
                        return (
                            <LemonButton
                                key={key}
                                type="tertiary"
                                size="small"
                                fullWidth
                                icon={
                                    <LemonCheckbox
                                        checked={mandatory || visibleColumns.includes(key)}
                                        className="pointer-events-none"
                                    />
                                }
                                disabledReason={mandatory ? 'This column identifies the ticket' : undefined}
                                onClick={() => toggleColumn(key)}
                            >
                                {ticketColumnLabel(key)}
                            </LemonButton>
                        )
                    })}
                    <LemonDivider className="my-1" />
                    <LemonButton
                        type="tertiary"
                        size="small"
                        fullWidth
                        disabledReason={allShown ? 'Every column is already shown' : undefined}
                        onClick={() => setVisibleColumns(offerable)}
                    >
                        Show all columns
                    </LemonButton>
                </div>
            }
        >
            <LemonButton
                type="secondary"
                size="small"
                icon={<IconTuning />}
                sideIcon={<IconChevronDown />}
                data-attr="support-tickets-column-selector"
            >
                {allShown ? 'All columns' : `${shownCount} of ${offerable.length} columns`}
            </LemonButton>
        </LemonDropdown>
    )
}
