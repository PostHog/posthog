import { useActions, useValues } from 'kea'

import { IconSearch } from '@posthog/icons'
import { InputGroup, InputGroupAddon, InputGroupInput, ToggleGroup, ToggleGroupItem } from '@posthog/quill'

import {
    ASSIGNEE_FILTERS,
    AssigneeFilter,
    warehouseSuggestionsSectionLogic,
} from 'products/warehouse_suggestions/frontend/warehouseSuggestionsSectionLogic'

import { CatalogSuggestionsFilterMenu } from './CatalogSuggestionsFilterMenu'

const ASSIGNEE_LABELS: Record<AssigneeFilter, string> = {
    anyone: 'All',
    me: 'Assigned to me',
    unassigned: 'Unassigned',
}

export function CatalogSuggestionsToolbar(): JSX.Element {
    const { filters, assigneeCounts } = useValues(warehouseSuggestionsSectionLogic)
    const { setFilters } = useActions(warehouseSuggestionsSectionLogic)

    return (
        <div className="flex flex-wrap items-center gap-2">
            <InputGroup size="sm" className="w-full @min-[40rem]/main-content:w-72">
                <InputGroupAddon>
                    <IconSearch />
                </InputGroupAddon>
                <InputGroupInput
                    type="search"
                    placeholder="Search by name"
                    aria-label="Search suggestions by name"
                    value={filters.search}
                    onChange={(event) => setFilters({ search: event.target.value })}
                    data-attr="data-catalog-suggestions-search"
                />
            </InputGroup>
            <CatalogSuggestionsFilterMenu />
            <ToggleGroup
                variant="default"
                aria-label="Assignee"
                value={[filters.assignee]}
                onValueChange={(value: string[]) => value[0] && setFilters({ assignee: value[0] as AssigneeFilter })}
            >
                {ASSIGNEE_FILTERS.map((assignee) => (
                    <ToggleGroupItem
                        key={assignee}
                        value={assignee}
                        data-attr={`data-catalog-suggestions-assignee-${assignee}`}
                    >
                        {ASSIGNEE_LABELS[assignee]}
                        <span translate="no" className="tabular-nums text-muted-foreground">
                            {assigneeCounts[assignee]}
                        </span>
                    </ToggleGroupItem>
                ))}
            </ToggleGroup>
        </div>
    )
}
