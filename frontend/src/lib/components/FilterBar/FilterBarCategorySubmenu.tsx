import { useActions, useValues } from 'kea'

import {
    DropdownMenuFilterProvider,
    DropdownMenuInput,
    DropdownMenuItem,
    DropdownMenuList,
    DropdownMenuSub,
    DropdownMenuSubContent,
    DropdownMenuSubTrigger,
    MenuEmpty,
    Spinner,
} from '@posthog/quill'

import { FilterBarCategoryIcon } from './FilterBarCategoryIcon'
import { filterBarLogic } from './filterBarLogic'
import { FilterBarCategory } from './filterBarTypes'

/** One category of the picker: a submenu with its own search over the fields the API knows for it. */
export function FilterBarCategorySubmenu({ category }: { category: FilterBarCategory }): JSX.Element {
    const { categoryFields, categoryFieldsLoading, categoryQueries } = useValues(filterBarLogic)
    const { setCategoryQuery, loadCategoryFields, addField } = useActions(filterBarLogic)
    const fields = categoryFields[category.id]
    const query = categoryQueries[category.id] ?? ''

    return (
        <DropdownMenuFilterProvider
            filter={null}
            value={query}
            onValueChange={(next) => setCategoryQuery(category.id, next)}
            autoHighlight
        >
            <DropdownMenuSub
                onOpenChange={(open) => {
                    if (open && !fields) {
                        loadCategoryFields({ categoryId: category.id })
                    }
                }}
            >
                <DropdownMenuSubTrigger data-attr={`filter-bar-category-${category.id}`}>
                    <FilterBarCategoryIcon categoryId={category.id} />
                    {category.label}
                </DropdownMenuSubTrigger>
                <DropdownMenuSubContent
                    className="w-64"
                    header={
                        <DropdownMenuInput
                            aria-label={`Search ${category.plural}`}
                            placeholder={`Search ${category.plural}…`}
                        />
                    }
                >
                    <DropdownMenuList>
                        {!fields ? (
                            <MenuEmpty>
                                <Spinner />
                                Loading…
                            </MenuEmpty>
                        ) : fields.length === 0 ? (
                            <MenuEmpty>
                                {query.trim()
                                    ? `No ${category.plural} match "${query.trim()}"`
                                    : `No ${category.plural} yet`}
                            </MenuEmpty>
                        ) : (
                            fields.map((field) => (
                                <DropdownMenuItem
                                    key={field.key}
                                    closeOnClick={false}
                                    onClick={() => addField(field, 'category')}
                                    tooltip={field.description || undefined}
                                    data-attr="filter-bar-field-category"
                                >
                                    <span className="truncate">{field.label}</span>
                                    {category.id !== 'cohorts' && field.label !== field.key && (
                                        <span className="ms-auto truncate font-mono text-xs text-muted-foreground">
                                            {field.key}
                                        </span>
                                    )}
                                </DropdownMenuItem>
                            ))
                        )}
                        {fields && categoryFieldsLoading && (
                            <MenuEmpty>
                                <Spinner />
                            </MenuEmpty>
                        )}
                    </DropdownMenuList>
                </DropdownMenuSubContent>
            </DropdownMenuSub>
        </DropdownMenuFilterProvider>
    )
}
