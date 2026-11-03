import { useActions, useValues } from 'kea'

import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator } from '@posthog/quill'

import { TodayFilterMenuTrigger } from '~/layout/today/TodayFilterMenuTrigger'
import { TodayRecentRadioSubmenu } from '~/layout/today/TodayRecentRadioSubmenu'

import { DEFAULT_RELATIONSHIPS_FILTERS, RelationshipStatusFilter, relationshipsLogic } from '../relationshipsLogic'

const STATUS_OPTIONS: { value: RelationshipStatusFilter; label: string }[] = [
    { value: 'all', label: 'All' },
    { value: 'pending', label: 'Pending' },
    { value: 'active', label: 'Active' },
    { value: 'rejected', label: 'Rejected' },
]

export function CatalogRelationshipsFilterMenu(): JSX.Element {
    const { filters } = useValues(relationshipsLogic)
    const { setFilters } = useActions(relationshipsLogic)
    const filtersActive = filters.status !== DEFAULT_RELATIONSHIPS_FILTERS.status

    return (
        <DropdownMenu>
            <TodayFilterMenuTrigger active={filtersActive} dataAttr="data-catalog-relationships-filter" />
            <DropdownMenuContent align="start" className="min-w-56">
                <TodayRecentRadioSubmenu
                    label="Status"
                    options={STATUS_OPTIONS}
                    value={filters.status}
                    defaultValue={DEFAULT_RELATIONSHIPS_FILTERS.status}
                    onChange={(status) => setFilters({ status })}
                    dataAttr="data-catalog-relationships-filter-status"
                />
                {filtersActive && (
                    <>
                        <DropdownMenuSeparator />
                        <DropdownMenuItem
                            variant="destructive"
                            onClick={() => setFilters({ status: DEFAULT_RELATIONSHIPS_FILTERS.status })}
                            data-attr="data-catalog-relationships-filter-clear"
                        >
                            Clear filters
                        </DropdownMenuItem>
                    </>
                )}
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
