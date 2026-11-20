import { useActions, useValues } from 'kea'

import {
    DropdownMenu,
    DropdownMenuCheckboxItem,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuSeparator,
    DropdownMenuSub,
    DropdownMenuSubContent,
    DropdownMenuSubTrigger,
    FilterMenuTrigger,
    cn,
} from '@posthog/quill'

import { LINEAGE_FILTER_TYPES, modelsLineageLogic } from './modelsLineageLogic'
import { NODE_TYPE_TAG_SETTINGS } from './nodeStyles'

function typeFilterLabel(selectedCount: number): string {
    if (selectedCount === LINEAGE_FILTER_TYPES.length) {
        return 'All types'
    }
    return selectedCount === 0 ? 'No types' : `${selectedCount} of ${LINEAGE_FILTER_TYPES.length}`
}

export function QuillLineageTypeFilterMenu(): JSX.Element {
    const { typeFilter, isFiltered } = useValues(modelsLineageLogic)
    const { setTypeFilter, resetFilters } = useActions(modelsLineageLogic)
    const allSelected = typeFilter.length === LINEAGE_FILTER_TYPES.length

    return (
        <DropdownMenu>
            <FilterMenuTrigger active={isFiltered} dataAttr="models-lineage-type-filter" />
            <DropdownMenuContent align="start" className="min-w-56">
                <DropdownMenuSub>
                    <DropdownMenuSubTrigger>
                        <span>Type</span>
                        <span
                            className={cn(
                                'flex-1 truncate pl-4 text-right',
                                allSelected ? 'text-muted-foreground' : 'text-primary'
                            )}
                        >
                            {typeFilterLabel(typeFilter.length)}
                        </span>
                    </DropdownMenuSubTrigger>
                    <DropdownMenuSubContent>
                        <DropdownMenuCheckboxItem
                            checked={allSelected}
                            closeOnClick={false}
                            onCheckedChange={(checked) => setTypeFilter(checked ? LINEAGE_FILTER_TYPES : [])}
                            data-attr="models-lineage-type-filter-all"
                        >
                            All types
                        </DropdownMenuCheckboxItem>
                        <DropdownMenuSeparator />
                        {LINEAGE_FILTER_TYPES.map((type) => (
                            <DropdownMenuCheckboxItem
                                key={type}
                                checked={typeFilter.includes(type)}
                                closeOnClick={false}
                                onCheckedChange={(checked) =>
                                    setTypeFilter(
                                        checked
                                            ? LINEAGE_FILTER_TYPES.filter(
                                                  (option) => option === type || typeFilter.includes(option)
                                              )
                                            : typeFilter.filter((option) => option !== type)
                                    )
                                }
                                data-attr="models-lineage-type-filter-option"
                            >
                                {NODE_TYPE_TAG_SETTINGS[type].label}
                            </DropdownMenuCheckboxItem>
                        ))}
                    </DropdownMenuSubContent>
                </DropdownMenuSub>
                {isFiltered && (
                    <>
                        <DropdownMenuSeparator />
                        <DropdownMenuItem
                            variant="destructive"
                            onClick={resetFilters}
                            data-attr="models-lineage-reset-filters"
                        >
                            Clear filters
                        </DropdownMenuItem>
                    </>
                )}
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
