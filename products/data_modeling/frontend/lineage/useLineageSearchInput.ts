import { useActions, useValues } from 'kea'
import { KeyboardEvent, RefObject, useRef } from 'react'

import { modelsLineageLogic } from './modelsLineageLogic'

export interface LineageSearchInput {
    searchInputRef: RefObject<HTMLInputElement>
    onSearchKeyDown: (event: KeyboardEvent<HTMLInputElement>) => void
    onSelectResult: (nodeId: string) => void
    onPreviousResult: () => void
    onNextResult: () => void
}

export function useLineageSearchInput(): LineageSearchInput {
    const searchInputRef = useRef<HTMLInputElement>(null)
    const { searchTerm, searchResults, showSearchResults, selectedSearchResult } = useValues(modelsLineageLogic)
    const { setSearchTerm, setDebouncedSearchTerm, moveSearchResult, focusSearchResult } =
        useActions(modelsLineageLogic)

    const focusSearchInput = (): void => {
        const input = searchInputRef.current
        input?.focus()
        const trimmedSearchTerm = searchTerm.trimEnd()
        if (input && trimmedSearchTerm.length > 1 && trimmedSearchTerm.endsWith('+')) {
            const trailingSelectorPosition = trimmedSearchTerm.length - 1
            input.setSelectionRange(trailingSelectorPosition, trailingSelectorPosition)
        }
    }

    return {
        searchInputRef,
        onSearchKeyDown: (event) => {
            if (
                showSearchResults &&
                searchResults.length > 0 &&
                (event.key === 'ArrowUp' || event.key === 'ArrowDown')
            ) {
                event.preventDefault()
                // Focus stays in the input here, so there is nothing to restore. Calling
                // focusSearchInput would move the caret away from where the user put it.
                moveSearchResult(event.key === 'ArrowUp' ? 'previous' : 'next', false)
            } else if (event.key === 'Enter' && selectedSearchResult) {
                event.preventDefault()
                focusSearchResult(selectedSearchResult.id, 'keyboard')
                focusSearchInput()
            } else if (event.key === 'Escape' && searchTerm) {
                event.preventDefault()
                setSearchTerm('')
                setDebouncedSearchTerm('')
            }
        },
        onSelectResult: (nodeId) => {
            focusSearchResult(nodeId, 'click')
            focusSearchInput()
        },
        onPreviousResult: () => {
            moveSearchResult('previous', true)
            focusSearchInput()
        },
        onNextResult: () => {
            moveSearchResult('next', true)
            focusSearchInput()
        },
    }
}
