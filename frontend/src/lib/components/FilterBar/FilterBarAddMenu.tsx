import { useActions, useValues } from 'kea'

import { IconFilter, IconPlus } from '@posthog/icons'
import {
    Button,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuFilterProvider,
    DropdownMenuTrigger,
} from '@posthog/quill'

import { FilterBarFieldRows } from './FilterBarFieldRows'
import { fieldFromFilter } from './filterBarFields'
import { FilterBarStage, filterBarLogic } from './filterBarLogic'
import { FilterBarMenuHeader } from './FilterBarMenuHeader'
import { FilterBarSaveRows } from './FilterBarSaveRows'
import { FilterBarValueRows } from './FilterBarValueRows'

function inputCopyForStage(
    stage: FilterBarStage,
    fieldLabel?: string,
    categoryPlural?: string
): { label: string; placeholder: string } {
    switch (stage) {
        case 'category':
            return { label: `Search ${categoryPlural}`, placeholder: `Search ${categoryPlural}…` }
        case 'values':
            return { label: 'Search or type a value', placeholder: `${fieldLabel ?? 'Value'}…` }
        case 'save':
            return { label: 'Name for these filters', placeholder: 'Name for these filters…' }
        default:
            return { label: 'Search fields', placeholder: 'Filter by…' }
    }
}

/**
 * The picker behind the add button. One menu, one search field, four screens: the fields to filter on, the
 * fields of one category, the values of the field just picked, and the name prompt when saving the current filters.
 * With `targetId`, a pick joins that group or event instead of the top level.
 */
export function FilterBarAddMenu({
    targetId = null,
    label,
}: {
    targetId?: number | null
    /** Renders a labelled button for the rows of the stacked editor, where the icon alone reads as nothing. */
    label?: string
}): JSX.Element {
    const { menuOpen, stackedOpen, addTargetId, query, stage, editingItem, browsingCategoryId, categoriesById } =
        useValues(filterBarLogic)
    const { setMenuOpen, setQuery } = useActions(filterBarLogic)

    const input = inputCopyForStage(
        stage,
        editingItem ? fieldFromFilter(editingItem.filter)?.label : undefined,
        browsingCategoryId ? categoriesById[browsingCategoryId]?.plural : undefined
    )

    return (
        <DropdownMenuFilterProvider filter={null} value={query} onValueChange={setQuery} autoHighlight>
            <DropdownMenu
                // The bar's own button and the editor's top-level button share a target, and only the visible flow opens.
                open={menuOpen && addTargetId === targetId && (!!label || !stackedOpen)}
                onOpenChange={(open) => setMenuOpen(open, targetId)}
                modal={false}
            >
                {label ? (
                    <DropdownMenuTrigger render={<Button />} data-attr="filter-bar-add-nested">
                        <IconPlus />
                        {label}
                    </DropdownMenuTrigger>
                ) : (
                    <DropdownMenuTrigger
                        render={<Button size="icon" variant="outline" aria-label="Add filter" tooltip="Add filter" />}
                        data-attr="filter-bar-add"
                    >
                        <IconFilter />
                    </DropdownMenuTrigger>
                )}
                <DropdownMenuContent
                    className="w-72"
                    header={<FilterBarMenuHeader label={input.label} placeholder={input.placeholder} />}
                >
                    {stage === 'values' && editingItem ? (
                        <FilterBarValueRows item={editingItem} query={query} />
                    ) : stage === 'save' ? (
                        <FilterBarSaveRows />
                    ) : (
                        <FilterBarFieldRows />
                    )}
                </DropdownMenuContent>
            </DropdownMenu>
        </DropdownMenuFilterProvider>
    )
}
