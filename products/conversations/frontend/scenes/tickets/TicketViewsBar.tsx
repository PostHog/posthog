import clsx from 'clsx'
import { useActions, useMountedLogic, useValues } from 'kea'

import { IconRefresh } from '@posthog/icons'
import { LemonButton, Tooltip } from '@posthog/lemon-ui'

import { pluralize } from 'lib/utils/strings'

import { SavedViewsPicker } from '../../components/SavedViews/SavedViewsPicker'
import { supportTicketsSceneLogic } from './supportTicketsSceneLogic'
import { TicketColumnsDropdown } from './TicketColumnsDropdown'

interface TicketViewsBarProps {
    embedded?: boolean
}

export function TicketViewsBar({ embedded = false }: TicketViewsBarProps): JSX.Element {
    const logic = useMountedLogic(supportTicketsSceneLogic)
    const { ticketsLoading, totalCount, hasActiveFilters, searchQuery, aiEnabled } = useValues(logic)
    const { loadTickets } = useActions(logic)

    return (
        <div className="flex flex-wrap items-center justify-between gap-2">
            <SavedViewsPicker />
            <div className="flex items-center gap-1">
                <Tooltip
                    title={
                        hasActiveFilters || searchQuery
                            ? 'Tickets matching the current filters, search, and view - not the total across all tickets'
                            : 'Tickets in the current view'
                    }
                >
                    {/* Count of tickets matching the current query, shown next to the view and filter
                        controls so it reads as the filtered count rather than an all-time total.
                        Hidden until the first load resolves; dims on subsequent background refreshes. */}
                    <span
                        className={clsx(
                            'text-secondary text-sm whitespace-nowrap px-1',
                            ticketsLoading && 'opacity-50'
                        )}
                        aria-live="polite"
                    >
                        {ticketsLoading && totalCount === 0 ? null : pluralize(totalCount, 'ticket')}
                    </span>
                </Tooltip>
                <TicketColumnsDropdown aiEnabled={aiEnabled} embedded={embedded} />
                <LemonButton
                    type="tertiary"
                    size="small"
                    icon={<IconRefresh />}
                    tooltip="Refresh"
                    aria-label="Refresh"
                    loading={ticketsLoading}
                    disabledReason={ticketsLoading ? 'Loading tickets...' : undefined}
                    onClick={loadTickets}
                    data-attr="refresh-tickets"
                />
            </div>
        </div>
    )
}
