import { useActions, useValues } from 'kea'

import { SearchAutocomplete } from 'lib/components/SearchAutocomplete/SearchAutocomplete'

import { queryDatabaseLogic } from './queryDatabaseLogic'

interface TreeSearchFieldProps {
    placeholder?: string
}

export function DatabaseSearchField({ placeholder }: TreeSearchFieldProps): JSX.Element {
    const { treeRef } = useValues(queryDatabaseLogic)
    const { searchTerm } = useValues(queryDatabaseLogic)
    const { setSearchTerm, clearSearch } = useActions(queryDatabaseLogic)

    function handleKeyDown(e: React.KeyboardEvent<HTMLInputElement>): void {
        if (e.key === 'ArrowDown') {
            e.preventDefault() // Prevent scrolling
            const visibleItems = treeRef?.current?.getVisibleItems()
            if (visibleItems && visibleItems.length > 0) {
                e.currentTarget.blur() // Remove focus from input
                treeRef?.current?.focusItem(visibleItems[0].id)
            }
        }
    }

    return (
        <SearchAutocomplete
            inputPlaceholder={placeholder}
            includeNegation
            defaultValue={searchTerm}
            onKeyDown={(e) => handleKeyDown(e)}
            onClear={() => clearSearch()}
            onChange={(value) => setSearchTerm(value)}
            autoFocus={true}
        />
    )
}
