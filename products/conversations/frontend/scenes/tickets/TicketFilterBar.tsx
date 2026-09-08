import { useActions, useMountedLogic, useValues } from 'kea'

import { IconPlusSmall } from '@posthog/icons'
import { LemonButton, LemonInput, LemonMenu } from '@posthog/lemon-ui'

import { supportTicketsSceneLogic } from './supportTicketsSceneLogic'
import { TICKET_FILTER_LABELS, ticketFilterBarLogic } from './ticketFilterBarLogic'
import { TicketFilterChip } from './TicketFilterChip'

export function TicketFilterBar(): JSX.Element {
    const logic = useMountedLogic(supportTicketsSceneLogic)
    const { searchQuery } = useValues(logic)
    const { setSearchQuery, resetFilters } = useActions(logic)
    const barLogic = ticketFilterBarLogic(logic.props)
    const { visibleFilterKeys, activeFilterKeys, addableFilterKeys, hasClearableFilters } = useValues(barLogic)
    const { openFilter } = useActions(barLogic)

    return (
        <div className="flex flex-wrap items-center gap-2">
            <LemonInput
                type="search"
                placeholder="Search by ticket #, name, email, or message..."
                value={searchQuery}
                onChange={setSearchQuery}
                size="small"
                className="min-w-64 grow max-w-96"
                // Matches MAX_SEARCH_LENGTH in ticket_filters.py — the backend ignores
                // longer searches and rejects saving them in a view.
                maxLength={200}
            />
            {visibleFilterKeys.map((filterKey) => (
                <TicketFilterChip
                    key={filterKey}
                    filterKey={filterKey}
                    autoOpen={!activeFilterKeys.includes(filterKey)}
                />
            ))}
            <LemonMenu
                items={addableFilterKeys.map((filterKey) => ({
                    label: TICKET_FILTER_LABELS[filterKey],
                    onClick: () => openFilter(filterKey),
                }))}
            >
                <LemonButton
                    type="tertiary"
                    size="small"
                    icon={<IconPlusSmall />}
                    disabledReason={addableFilterKeys.length === 0 ? 'Every filter is already shown' : undefined}
                    data-attr="add-ticket-filter"
                >
                    Filter
                </LemonButton>
            </LemonMenu>
            {hasClearableFilters && (
                <LemonButton
                    type="tertiary"
                    size="small"
                    onClick={resetFilters}
                    className="ml-auto"
                    data-attr="clear-ticket-filters"
                >
                    Clear filters
                </LemonButton>
            )}
        </div>
    )
}
