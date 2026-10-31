import { useValues } from 'kea'

import {
    DropdownMenuGroup,
    DropdownMenuItem,
    DropdownMenuLabel,
    DropdownMenuList,
    DropdownMenuSeparator,
    MenuEmpty,
    Spinner,
} from '@posthog/quill'

import { useFilterBarFieldPicker } from './filterBarFieldPicker'
import { filterBarLogic } from './filterBarLogic'
import { FilterBarCategory, FilterBarField } from './filterBarTypes'

export function FilterBarCategoryRows({ category }: { category: FilterBarCategory }): JSX.Element {
    const { categoryFields, categoryFieldsLoading, categoryQueries } = useValues(filterBarLogic)
    const { pick } = useFilterBarFieldPicker()
    const fields = categoryFields[category.id]
    const query = (categoryQueries[category.id] ?? '').trim()
    const projectFields = fields?.filter((field) => field.group === 'project') ?? []
    const posthogFields = fields?.filter((field) => field.group === 'posthog') ?? []
    const flatFields = fields?.filter((field) => !field.group) ?? []

    const fieldRow = (field: FilterBarField): JSX.Element => (
        <DropdownMenuItem
            key={field.key}
            closeOnClick={false}
            onClick={() => pick(field, 'category')}
            tooltip={
                field.label !== field.key || field.description ? (
                    <span className="flex max-w-xs flex-col gap-1">
                        {field.label !== field.key && <code>{field.key}</code>}
                        {field.description && <span>{field.description}</span>}
                    </span>
                ) : undefined
            }
            data-attr="filter-bar-field-category"
        >
            <span className="truncate">{field.label}</span>
        </DropdownMenuItem>
    )

    return (
        <DropdownMenuList>
            {!fields ? (
                <MenuEmpty>
                    <Spinner />
                    Loading…
                </MenuEmpty>
            ) : fields.length === 0 ? (
                <MenuEmpty>{query ? `No ${category.plural} match "${query}"` : `No ${category.plural} yet`}</MenuEmpty>
            ) : (
                <>
                    {flatFields.map(fieldRow)}
                    {projectFields.length > 0 && (
                        <DropdownMenuGroup>
                            <DropdownMenuLabel>Your properties</DropdownMenuLabel>
                            {projectFields.map(fieldRow)}
                        </DropdownMenuGroup>
                    )}
                    {projectFields.length > 0 && posthogFields.length > 0 && <DropdownMenuSeparator />}
                    {posthogFields.length > 0 && (
                        <DropdownMenuGroup>
                            <DropdownMenuLabel>PostHog properties</DropdownMenuLabel>
                            {posthogFields.map(fieldRow)}
                        </DropdownMenuGroup>
                    )}
                    {(projectFields.length > 0 || posthogFields.length > 0) && (
                        <MenuEmpty>Search to see every {category.plural.replace(/ies$/, 'y')}</MenuEmpty>
                    )}
                </>
            )}
            {fields && categoryFieldsLoading && (
                <MenuEmpty>
                    <Spinner />
                </MenuEmpty>
            )}
        </DropdownMenuList>
    )
}
