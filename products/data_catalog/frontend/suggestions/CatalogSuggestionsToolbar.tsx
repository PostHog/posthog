import { useActions, useValues } from 'kea'

import { IconSearch } from '@posthog/icons'
import { InputGroup, InputGroupAddon, InputGroupInput } from '@posthog/quill'

import { warehouseSuggestionsSectionLogic } from 'products/warehouse_suggestions/frontend/warehouseSuggestionsSectionLogic'

import { CatalogSuggestionsFilterMenu } from './CatalogSuggestionsFilterMenu'

export function CatalogSuggestionsToolbar(): JSX.Element {
    const { filters } = useValues(warehouseSuggestionsSectionLogic)
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
        </div>
    )
}
