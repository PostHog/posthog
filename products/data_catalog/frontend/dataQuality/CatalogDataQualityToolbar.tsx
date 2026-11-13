import { useActions, useValues } from 'kea'

import { IconSearch } from '@posthog/icons'
import { InputGroup, InputGroupAddon, InputGroupInput, ToggleGroup, ToggleGroupItem } from '@posthog/quill'

import { CHECKS_SCOPES, ChecksScope, catalogDataQualityLogic } from './catalogDataQualityLogic'

const SCOPE_LABELS: Record<ChecksScope, string> = {
    all: 'All',
    failing: 'Failing',
}

export function CatalogDataQualityToolbar(): JSX.Element {
    const { search, scope, scopeCounts } = useValues(catalogDataQualityLogic)
    const { setSearch, setScope } = useActions(catalogDataQualityLogic)

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
                    data-attr="data-catalog-quality-search"
                />
            </InputGroup>
            <ToggleGroup
                variant="default"
                aria-label="Show"
                value={[scope]}
                onValueChange={(value: string[]) => value[0] && setScope(value[0] as ChecksScope)}
            >
                {CHECKS_SCOPES.map((option) => (
                    <ToggleGroupItem key={option} value={option} data-attr={`data-catalog-quality-scope-${option}`}>
                        {SCOPE_LABELS[option]}
                        <span translate="no" className="tabular-nums text-muted-foreground">
                            {scopeCounts[option]}
                        </span>
                    </ToggleGroupItem>
                ))}
            </ToggleGroup>
        </div>
    )
}
