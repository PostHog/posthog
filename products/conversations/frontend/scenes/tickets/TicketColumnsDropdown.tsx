import { useActions, useValues } from 'kea'

import { LemonButton, LemonCheckbox, LemonDivider, LemonDropdown } from '@posthog/lemon-ui'

import { IconTuning } from 'lib/lemon-ui/icons'

import { ticketColumnChoices } from './ticketColumns'
import { ticketColumnsLogic } from './ticketColumnsLogic'

interface TicketColumnsDropdownProps {
    aiEnabled: boolean
    embedded?: boolean
}

export function TicketColumnsDropdown({ aiEnabled, embedded = false }: TicketColumnsDropdownProps): JSX.Element {
    const { visibleColumns } = useValues(ticketColumnsLogic)
    const { toggleColumn, setVisibleColumns } = useActions(ticketColumnsLogic)

    const { offerable, choices, shownCount, allShown, showAllDisabledReason } = ticketColumnChoices(visibleColumns, {
        aiEnabled,
        embedded,
    })

    return (
        <LemonDropdown
            closeOnClickInside={false}
            overlay={
                <div className="space-y-px p-1 min-w-48">
                    {choices.map((choice) => (
                        <LemonButton
                            key={choice.key}
                            type="tertiary"
                            size="small"
                            fullWidth
                            icon={<LemonCheckbox checked={choice.shown} className="pointer-events-none" />}
                            disabledReason={choice.disabledReason}
                            onClick={() => toggleColumn(choice.key)}
                        >
                            {choice.label}
                        </LemonButton>
                    ))}
                    <LemonDivider className="my-1" />
                    <LemonButton
                        type="tertiary"
                        size="small"
                        fullWidth
                        disabledReason={showAllDisabledReason}
                        onClick={() => setVisibleColumns(offerable)}
                    >
                        Show all columns
                    </LemonButton>
                </div>
            }
        >
            <LemonButton
                type="tertiary"
                size="small"
                icon={<IconTuning />}
                data-attr="support-tickets-column-selector"
                tooltip={allShown ? 'Show all columns' : `Show ${shownCount} of ${offerable.length} columns`}
            />
        </LemonDropdown>
    )
}
