import { useActions, useValues } from 'kea'

import { LemonCheckbox } from '@posthog/lemon-ui'

import { SearchAutocomplete } from 'lib/components/SearchAutocomplete/SearchAutocomplete'

import { queryDatabaseLogic } from './queryDatabaseLogic'

interface TreeSearchFieldProps {
    placeholder?: string
}

export function DatabaseSearchField({ placeholder }: TreeSearchFieldProps): JSX.Element {
    const { treeRef, searchTerm, connectionId, showFailedMaterializationsOnly } = useValues(queryDatabaseLogic)
    const { setSearchTerm, clearSearch, setShowFailedMaterializationsOnly } = useActions(queryDatabaseLogic)

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
        <>
            <SearchAutocomplete
                inputPlaceholder={placeholder}
                includeNegation
                defaultValue={searchTerm}
                onKeyDown={(e) => handleKeyDown(e)}
                onClear={() => clearSearch()}
                onChange={(value) => setSearchTerm(value)}
            />
            {!connectionId && (
                <LemonCheckbox
                    label="Failed materializations only"
                    checked={showFailedMaterializationsOnly}
                    onChange={setShowFailedMaterializationsOnly}
                    data-attr="sql-editor-failed-materializations-filter"
                    size="small"
                />
            )}
        </>
    )
}
