import { useActions, useValues } from 'kea'

import { IconSearch } from '@posthog/icons'
import { InputGroup, InputGroupAddon, InputGroupInput, ToggleGroup, ToggleGroupItem } from '@posthog/quill'

import { TableScope } from '../catalogTableRows'
import { catalogTablesLogic } from '../catalogTablesLogic'
import { CatalogTablesFilterMenu } from './CatalogTablesFilterMenu'

const SCOPE_LABELS: Record<TableScope, string> = {
    all: 'All',
    attention: 'Needs attention',
}

const SCOPES: TableScope[] = ['all', 'attention']

export function CatalogTablesToolbar(): JSX.Element {
    const { search, scope, scopeCounts, rowsLoaded } = useValues(catalogTablesLogic)
    const { setSearch, setScope } = useActions(catalogTablesLogic)

    return (
        <div className="flex flex-wrap items-center gap-2">
            <InputGroup size="sm" className="w-full @min-[40rem]/main-content:w-72">
                <InputGroupAddon>
                    <IconSearch />
                </InputGroupAddon>
                <InputGroupInput
                    type="search"
                    placeholder="Search tables and views"
                    aria-label="Search tables and views"
                    value={search}
                    onChange={(event) => setSearch(event.target.value)}
                    data-attr="data-catalog-tables-search"
                />
            </InputGroup>
            <CatalogTablesFilterMenu />
            <ToggleGroup
                variant="default"
                aria-label="Show"
                value={[scope]}
                onValueChange={(value: string[]) => value[0] && setScope(value[0] as TableScope)}
            >
                {SCOPES.map((option) => (
                    <ToggleGroupItem key={option} value={option} data-attr={`data-catalog-tables-scope-${option}`}>
                        {SCOPE_LABELS[option]}
                        {rowsLoaded && (
                            <span translate="no" className="tabular-nums text-muted-foreground">
                                {scopeCounts[option]}
                            </span>
                        )}
                    </ToggleGroupItem>
                ))}
            </ToggleGroup>
        </div>
    )
}
