import { useActions, useValues } from 'kea'
import { ReactNode, useMemo, useState } from 'react'

import {
    Button,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuFilterProvider,
    DropdownMenuTrigger,
} from '@posthog/quill'

import { FilterBarFieldPicker, FilterBarFieldPickerContext } from './filterBarFieldPicker'
import { FilterBarFieldRows } from './FilterBarFieldRows'
import { filterBarLogic } from './filterBarLogic'
import { FilterBarMenuHeader } from './FilterBarMenuHeader'
import { FilterBarField } from './filterBarTypes'

/** The first segment of a chip that can change what it filters on. It opens the same field list as the add menu. */
export function FilterBarFieldSegment({
    purpose,
    onPick,
    children,
}: {
    purpose: 'replace-property' | 'replace-event'
    onPick: (field: FilterBarField) => void
    children: ReactNode
}): JSX.Element {
    const { query, browsingCategoryId, categoriesById } = useValues(filterBarLogic)
    const { setQuery, browseCategory } = useActions(filterBarLogic)
    const [open, setOpen] = useState(false)
    const searchPlural = browsingCategoryId ? categoriesById[browsingCategoryId]?.plural : null

    const close = (): void => {
        setOpen(false)
        setQuery('')
        browseCategory(null)
    }
    const picker = useMemo<FilterBarFieldPicker>(
        () => ({
            purpose,
            pick: (field) => {
                onPick(field)
                close()
            },
        }),
        // `close` only calls stable kea actions and a state setter.
        // oxlint-disable-next-line react-hooks/exhaustive-deps
        [purpose, onPick]
    )

    return (
        <FilterBarFieldPickerContext.Provider value={picker}>
            <DropdownMenuFilterProvider filter={null} value={query} onValueChange={setQuery} autoHighlight>
                <DropdownMenu
                    open={open}
                    onOpenChange={(next) => {
                        if (!next) {
                            close()
                            return
                        }
                        setOpen(true)
                        if (purpose === 'replace-event') {
                            browseCategory('events')
                        }
                    }}
                    modal={false}
                >
                    <DropdownMenuTrigger
                        render={<Button variant="outline" className="min-w-0" />}
                        data-attr="filter-bar-chip-field"
                    >
                        {children}
                    </DropdownMenuTrigger>
                    <DropdownMenuContent
                        className="w-72"
                        header={
                            <FilterBarMenuHeader
                                label={searchPlural ? `Search ${searchPlural}` : 'Search fields'}
                                placeholder={searchPlural ? `Search ${searchPlural}…` : 'Filter by…'}
                            />
                        }
                    >
                        <FilterBarFieldRows />
                    </DropdownMenuContent>
                </DropdownMenu>
            </DropdownMenuFilterProvider>
        </FilterBarFieldPickerContext.Provider>
    )
}
