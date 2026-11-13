import { useActions, useValues } from 'kea'

import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuSeparator,
    FilterMenuTrigger,
} from '@posthog/quill'

import { TodayRecentRadioSubmenu } from '~/layout/today/TodayRecentRadioSubmenu'

import {
    AssigneeFilter,
    DEFAULT_SECTION_FILTERS,
    KindFilter,
    SubjectFilter,
    warehouseSuggestionsSectionLogic,
} from 'products/warehouse_suggestions/frontend/warehouseSuggestionsSectionLogic'

const KIND_OPTIONS: { value: KindFilter; label: string }[] = [
    { value: 'any', label: 'All kinds' },
    { value: 'materialize', label: 'Materialize' },
    { value: 'unmaterialize', label: 'Stop materializing' },
    { value: 'certify', label: 'Certify' },
    { value: 'deprecate', label: 'Mark deprecated' },
]

const ASSIGNEE_OPTIONS: { value: AssigneeFilter; label: string }[] = [
    { value: 'anyone', label: 'Anyone' },
    { value: 'me', label: 'Assigned to me' },
    { value: 'unassigned', label: 'Unassigned' },
]

const SUBJECT_OPTIONS: { value: SubjectFilter; label: string }[] = [
    { value: 'any', label: 'Tables and views' },
    { value: 'tables', label: 'Tables' },
    { value: 'views', label: 'Views' },
]

export function CatalogSuggestionsFilterMenu(): JSX.Element {
    const { filters, filtersActive } = useValues(warehouseSuggestionsSectionLogic)
    const { setFilters, clearFilters } = useActions(warehouseSuggestionsSectionLogic)

    return (
        <DropdownMenu>
            <FilterMenuTrigger active={filtersActive} dataAttr="data-catalog-suggestions-filter" />
            <DropdownMenuContent align="start" className="min-w-56">
                <TodayRecentRadioSubmenu
                    label="Kind"
                    options={KIND_OPTIONS}
                    value={filters.kind}
                    defaultValue={DEFAULT_SECTION_FILTERS.kind}
                    onChange={(kind) => setFilters({ kind })}
                    dataAttr="data-catalog-suggestions-filter-kind"
                />
                <TodayRecentRadioSubmenu
                    label="Assignee"
                    options={ASSIGNEE_OPTIONS}
                    value={filters.assignee}
                    defaultValue={DEFAULT_SECTION_FILTERS.assignee}
                    onChange={(assignee) => setFilters({ assignee })}
                    dataAttr="data-catalog-suggestions-filter-assignee"
                />
                <TodayRecentRadioSubmenu
                    label="Type"
                    options={SUBJECT_OPTIONS}
                    value={filters.subject}
                    defaultValue={DEFAULT_SECTION_FILTERS.subject}
                    onChange={(subject) => setFilters({ subject })}
                    dataAttr="data-catalog-suggestions-filter-type"
                />
                {filtersActive && (
                    <>
                        <DropdownMenuSeparator />
                        <DropdownMenuItem
                            variant="destructive"
                            onClick={clearFilters}
                            data-attr="data-catalog-suggestions-filter-clear"
                        >
                            Clear filters
                        </DropdownMenuItem>
                    </>
                )}
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
