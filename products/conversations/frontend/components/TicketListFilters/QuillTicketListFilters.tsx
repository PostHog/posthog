import { useActions, useMountedLogic, useValues } from 'kea'

import { IconRefresh, IconSearch } from '@posthog/icons'
import {
    Button,
    InputGroup,
    InputGroupAddon,
    InputGroupInput,
    InputGroupText,
    Text,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
    cn,
} from '@posthog/quill'

import { pluralize } from 'lib/utils/strings'

import { supportTicketsSceneLogic } from '../../scenes/tickets/supportTicketsSceneLogic'
import { QuillTicketDateFilter } from '../QuillTicketDateFilter/QuillTicketDateFilter'
import { QuillTicketFilterMenu } from '../QuillTicketFilterMenu/QuillTicketFilterMenu'
import { QuillSavedViewsButton } from '../SavedViews/QuillSavedViewsButton'

const SEARCH_PLACEHOLDER = 'Search by ticket #, name, email, or message...'

/** Search, the one filter menu beside it, the date range, saved views, and the ticket count with a refresh. */
export function QuillTicketListFilters(): JSX.Element {
    const logic = useMountedLogic(supportTicketsSceneLogic)
    const { searchQuery, ticketsLoading, totalCount, hasActiveFilters } = useValues(logic)
    const { setSearchQuery, loadTickets } = useActions(logic)

    return (
        <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex min-w-0 flex-1 flex-wrap items-center gap-2">
                <InputGroup size="sm" className="w-72 min-w-0 max-w-full">
                    <InputGroupAddon align="inline-start">
                        <InputGroupText>
                            <IconSearch />
                        </InputGroupText>
                    </InputGroupAddon>
                    <InputGroupInput
                        type="search"
                        aria-label={SEARCH_PLACEHOLDER}
                        placeholder={SEARCH_PLACEHOLDER}
                        value={searchQuery}
                        onChange={(event: React.ChangeEvent<HTMLInputElement>) => setSearchQuery(event.target.value)}
                        // Matches MAX_SEARCH_LENGTH in ticket_filters.py — the backend ignores
                        // longer searches and rejects saving them in a view.
                        maxLength={200}
                    />
                </InputGroup>
                <QuillTicketFilterMenu />
                <QuillTicketDateFilter />
                <QuillSavedViewsButton id="SupportTicketsScene" />
            </div>
            <div className="flex items-center gap-1">
                <Tooltip>
                    <TooltipTrigger
                        render={
                            <Text
                                size="xs"
                                variant="muted"
                                render={<span />}
                                aria-live="polite"
                                className={cn('whitespace-nowrap', ticketsLoading && 'opacity-50')}
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
                <Button
                    size="icon"
                    aria-label="Refresh"
                    tooltip="Refresh"
                    loading={ticketsLoading}
                    onClick={() => loadTickets()}
                    data-attr="refresh-tickets"
                >
                    <IconRefresh />
                </Button>
            </div>
        </div>
    )
}
