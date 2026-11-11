import { useActions, useValues } from 'kea'

import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuSeparator,
    FilterMenuTrigger,
} from '@posthog/quill'

import { TodayRecentRadioSubmenu } from '~/layout/today/TodayRecentRadioSubmenu'

import { ISSUE_KIND_ORDER, ISSUE_LABELS } from 'products/data_modeling/frontend/overviewIssueCopy'

import {
    CHECKS_FILTER_OPTIONS,
    DEFAULT_TABLES_FILTERS,
    KIND_LABELS,
    TablesFilters,
    TrustFilter,
} from '../catalogTableRows'
import { catalogTablesLogic } from '../catalogTablesLogic'

const KIND_OPTIONS: { value: TablesFilters['kind']; label: string }[] = [
    { value: 'any', label: 'All types' },
    { value: 'posthog', label: KIND_LABELS.posthog },
    { value: 'source', label: KIND_LABELS.source },
    { value: 'self_managed', label: KIND_LABELS.self_managed },
    { value: 'view', label: KIND_LABELS.view },
    { value: 'materialized_view', label: KIND_LABELS.materialized_view },
]

const PROBLEM_OPTIONS: { value: TablesFilters['problem']; label: string }[] = [
    { value: 'any', label: 'Any' },
    ...ISSUE_KIND_ORDER.map((kind) => ({ value: kind, label: ISSUE_LABELS[kind] })),
]

const TRUST_OPTIONS: { value: TrustFilter; label: string }[] = [
    { value: 'any', label: 'Any' },
    { value: 'certified', label: 'Certified' },
    { value: 'proposed', label: 'Proposed' },
    { value: 'deprecated', label: 'Deprecated' },
    { value: 'none', label: 'No trust mark' },
]

export function CatalogTablesFilterMenu(): JSX.Element {
    const { filters, filtersActive } = useValues(catalogTablesLogic)
    const { setFilters, clearFilters } = useActions(catalogTablesLogic)

    return (
        <DropdownMenu>
            <FilterMenuTrigger active={filtersActive} dataAttr="data-catalog-tables-filter" />
            <DropdownMenuContent align="start" className="min-w-56">
                <TodayRecentRadioSubmenu
                    label="Type"
                    options={KIND_OPTIONS}
                    value={filters.kind}
                    defaultValue={DEFAULT_TABLES_FILTERS.kind}
                    onChange={(kind) => setFilters({ kind })}
                    dataAttr="data-catalog-tables-filter-type"
                />
                <TodayRecentRadioSubmenu
                    label="Problem"
                    options={PROBLEM_OPTIONS}
                    value={filters.problem}
                    defaultValue={DEFAULT_TABLES_FILTERS.problem}
                    onChange={(problem) => setFilters({ problem })}
                    dataAttr="data-catalog-tables-filter-problem"
                />
                <TodayRecentRadioSubmenu
                    label="Trust"
                    options={TRUST_OPTIONS}
                    value={filters.trust}
                    defaultValue={DEFAULT_TABLES_FILTERS.trust}
                    onChange={(trust) => setFilters({ trust })}
                    dataAttr="data-catalog-tables-filter-trust"
                />
                <TodayRecentRadioSubmenu
                    label="Checks"
                    options={CHECKS_FILTER_OPTIONS}
                    value={filters.checks}
                    defaultValue={DEFAULT_TABLES_FILTERS.checks}
                    onChange={(checks) => setFilters({ checks })}
                    dataAttr="data-catalog-tables-filter-checks"
                />
                {filtersActive && (
                    <>
                        <DropdownMenuSeparator />
                        <DropdownMenuItem
                            variant="destructive"
                            onClick={clearFilters}
                            data-attr="data-catalog-tables-filter-clear"
                        >
                            Clear filters
                        </DropdownMenuItem>
                    </>
                )}
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
