import { useActions, useValues } from 'kea'

import { IconChevronLeft } from '@posthog/icons'
import { Button, DropdownMenuInput } from '@posthog/quill'

import { useFilterBarFieldPicker } from './filterBarFieldPicker'
import { filterBarLogic } from './filterBarLogic'

/**
 * The header of a field picker: the search field, and while a category is open, a way back to the first screen.
 * The back control sits here rather than in the list, so the menu's first highlighted row is always a field.
 */
export function FilterBarMenuHeader({ label, placeholder }: { label: string; placeholder: string }): JSX.Element {
    const { browsingCategoryId, categoriesById } = useValues(filterBarLogic)
    const { browseCategory } = useActions(filterBarLogic)
    const { purpose } = useFilterBarFieldPicker()
    // An event chip's picker has no first screen to go back to.
    const category = browsingCategoryId && purpose !== 'replace-event' ? categoriesById[browsingCategoryId] : null

    return (
        <>
            <DropdownMenuInput aria-label={label} placeholder={placeholder} />
            {category && (
                <div className="shrink-0 border-b border-border p-1">
                    <Button
                        size="row"
                        className="w-full justify-start"
                        // Keeps focus in the search field, so typing and arrow keys keep working after going back.
                        onMouseDown={(event) => event.preventDefault()}
                        onClick={() => browseCategory(null)}
                        data-attr="filter-bar-category-back"
                    >
                        <IconChevronLeft />
                        {category.label}
                    </Button>
                </div>
            )}
        </>
    )
}
