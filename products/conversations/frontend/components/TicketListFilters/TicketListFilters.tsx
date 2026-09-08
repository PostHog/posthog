import clsx from 'clsx'
import { useActions, useMountedLogic, useValues } from 'kea'

import { IconRefresh } from '@posthog/icons'
import { LemonButton, LemonInput, Tooltip } from '@posthog/lemon-ui'

import { pluralize } from 'lib/utils/strings'

import { supportTicketsSceneLogic } from '../../scenes/tickets/supportTicketsSceneLogic'
import { TicketColumnsDropdown } from '../../scenes/tickets/TicketColumnsDropdown'
import { SavedViewsButton } from '../SavedViews/SavedViewsButton'
import { TicketAppliedFilters } from '../TicketAppliedFilters/TicketAppliedFilters'
import { TicketFiltersDropdown } from '../TicketFiltersDropdown/TicketFiltersDropdown'
import { TicketListBulkActions } from '../TicketListBulkActions/TicketListBulkActions'

interface TicketListFiltersProps {
    embedded?: boolean
}

export function TicketListFilters({ embedded = false }: TicketListFiltersProps): JSX.Element {
    const logic = useMountedLogic(supportTicketsSceneLogic)
    const { searchQuery, ticketsLoading, totalCount, hasActiveFilters, aiEnabled } = useValues(logic)
    const { setSearchQuery, loadTickets } = useActions(logic)

    return (
        <div className="flex flex-col gap-2">
            <div className="flex flex-wrap gap-2 items-center justify-between">
                <div className="flex flex-wrap gap-2 items-center">
                    <LemonInput
                        type="search"
                        placeholder="Search by ticket #, name, email, or message..."
                        value={searchQuery}
                        onChange={setSearchQuery}
                        size="small"
                        className="min-w-64"
                        // Matches MAX_SEARCH_LENGTH in ticket_filters.py — the backend ignores
                        // longer searches and rejects saving them in a view.
                        maxLength={200}
                    />
                    <TicketFiltersDropdown />
                    <Tooltip
                        title={
                            hasActiveFilters || searchQuery
                                ? 'Tickets matching the current filters, search, and view, not the total across all tickets'
                                : 'Tickets in the current view'
                        }
                    >
                        <span
                            className={clsx('text-secondary text-sm whitespace-nowrap', ticketsLoading && 'opacity-50')}
                            aria-live="polite"
                        >
                            {ticketsLoading && totalCount === 0 ? null : pluralize(totalCount, 'ticket')}
                        </span>
                    </Tooltip>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                    <SavedViewsButton id="SupportTicketsScene" />
                    <LemonButton
                        type="secondary"
                        icon={<IconRefresh />}
                        loading={ticketsLoading}
                        disabledReason={ticketsLoading ? 'Loading tickets...' : undefined}
                        onClick={loadTickets}
                        size="small"
                        data-attr="refresh-tickets"
                    >
                        Refresh
                    </LemonButton>
                </div>
            </div>
            <TicketAppliedFilters />
            <div className="flex flex-wrap items-center justify-between gap-2">
                <TicketListBulkActions />
                <TicketColumnsDropdown aiEnabled={aiEnabled} embedded={embedded} />
            </div>
        </div>
    )
}
