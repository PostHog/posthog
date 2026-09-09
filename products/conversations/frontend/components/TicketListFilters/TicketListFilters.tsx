import clsx from 'clsx'
import { useActions, useMountedLogic, useValues } from 'kea'

import { IconRefresh, IconSearch } from '@posthog/icons'

import {
    Button,
    InputGroup,
    InputGroupAddon,
    InputGroupInput,
    Text,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from 'lib/ui/quill'
import { pluralize } from 'lib/utils/strings'

import { supportTicketsSceneLogic } from '../../scenes/tickets/supportTicketsSceneLogic'
import { TicketColumnsDropdown } from '../../scenes/tickets/TicketColumnsDropdown'
import { SavedViewsButton } from '../SavedViews/SavedViewsButton'
import { TicketAppliedFilters } from '../TicketAppliedFilters/TicketAppliedFilters'
import { TicketDateRangeButton } from '../TicketDateRangeButton/TicketDateRangeButton'
import { TicketFiltersDropdown } from '../TicketFiltersDropdown/TicketFiltersDropdown'
import { TicketListBulkActions } from '../TicketListBulkActions/TicketListBulkActions'

interface TicketListFiltersProps {
    embedded?: boolean
}

export function TicketListFilters({ embedded = false }: TicketListFiltersProps): JSX.Element {
    const logic = useMountedLogic(supportTicketsSceneLogic)
    const { searchQuery, ticketsLoading, totalCount, hasActiveFilters, aiEnabled, dateFrom, dateTo } = useValues(logic)
    const { setSearchQuery, loadTickets, setDateRange } = useActions(logic)

    return (
        <div className="flex flex-col gap-2" data-quill>
            <div className="flex flex-wrap gap-2 items-center justify-between">
                <div className="flex flex-wrap gap-2 items-center">
                    <div className="min-w-64 max-w-full shrink-0">
                        <InputGroup className="h-7">
                            <InputGroupAddon>
                                <IconSearch />
                            </InputGroupAddon>
                            <InputGroupInput
                                type="search"
                                placeholder="Search by ticket #, name, email, or message..."
                                value={searchQuery}
                                onChange={(event) => setSearchQuery(event.target.value)}
                                // Matches MAX_SEARCH_LENGTH in ticket_filters.py — the backend ignores
                                // longer searches and rejects saving them in a view.
                                maxLength={200}
                                aria-label="Search by ticket #, name, email, or message..."
                            />
                        </InputGroup>
                    </div>
                    <TicketDateRangeButton dateFrom={dateFrom} dateTo={dateTo} onChange={setDateRange} />
                    <TicketFiltersDropdown />
                    <SavedViewsButton id="SupportTicketsScene" />
                </div>
                <div className="flex flex-wrap items-center gap-2">
                    <Tooltip>
                        <TooltipTrigger
                            render={
                                <Text
                                    size="sm"
                                    variant="muted"
                                    render={<span />}
                                    className={clsx('whitespace-nowrap', ticketsLoading && 'opacity-50')}
                                    aria-live="polite"
                                />
                            }
                        >
                            {ticketsLoading && totalCount === 0 ? null : pluralize(totalCount, 'ticket')}
                        </TooltipTrigger>
                        <TooltipContent>
                            {hasActiveFilters || searchQuery
                                ? 'Tickets matching the current filters, search, and view, not the total across all tickets'
                                : 'Tickets in the current view'}
                        </TooltipContent>
                    </Tooltip>
                    <Tooltip>
                        <TooltipTrigger
                            render={
                                <Button
                                    variant="default"
                                    size="icon-sm"
                                    loading={ticketsLoading}
                                    disabled={ticketsLoading}
                                    onClick={loadTickets}
                                    data-attr="refresh-tickets"
                                    aria-label="Refresh"
                                />
                            }
                        >
                            <IconRefresh />
                        </TooltipTrigger>
                        <TooltipContent>Refresh</TooltipContent>
                    </Tooltip>
                    <TicketColumnsDropdown aiEnabled={aiEnabled} embedded={embedded} />
                </div>
            </div>
            <TicketAppliedFilters />
            <TicketListBulkActions />
        </div>
    )
}
