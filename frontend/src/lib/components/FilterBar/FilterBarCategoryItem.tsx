import { useActions } from 'kea'

import { IconChevronRight } from '@posthog/icons'
import { DropdownMenuItem } from '@posthog/quill'

import { FilterBarCategoryIcon } from './FilterBarCategoryIcon'
import { filterBarLogic } from './filterBarLogic'
import { FilterBarCategory } from './filterBarTypes'

export function FilterBarCategoryItem({ category }: { category: FilterBarCategory }): JSX.Element {
    const { browseCategory } = useActions(filterBarLogic)
    return (
        <DropdownMenuItem
            closeOnClick={false}
            onClick={() => browseCategory(category.id)}
            data-attr={`filter-bar-category-${category.id}`}
        >
            <FilterBarCategoryIcon categoryId={category.id} />
            {category.label}
            <IconChevronRight className="ms-auto" />
        </DropdownMenuItem>
    )
}
