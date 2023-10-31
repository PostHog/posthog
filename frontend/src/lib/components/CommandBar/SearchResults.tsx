import { useActions, useValues } from 'kea'
import { useEventListener } from 'lib/hooks/useEventListener'

import { searchBarLogic } from './searchBarLogic'
import SearchResult from './SearchResult'

const SearchResults = (): JSX.Element => {
    const { filterSearchResults, activeResultIndex, keyboardResultIndex, maxIndex } = useValues(searchBarLogic)
    const { onArrowUp, onArrowDown, openResult } = useActions(searchBarLogic)

    useEventListener('keydown', (event) => {
        if (!filterSearchResults) {
            return
        }

        if (event.key === 'Enter') {
            event.preventDefault()
            openResult(activeResultIndex)
        } else if (event.key === 'ArrowDown') {
            event.preventDefault()
            onArrowDown(activeResultIndex, maxIndex)
        } else if (event.key === 'ArrowUp') {
            event.preventDefault()
            onArrowUp(activeResultIndex, maxIndex)
        }
    })

    return (
        <div className="grow overscroll-none overflow-y-auto">
            {filterSearchResults?.map((result, index) => (
                <SearchResult
                    key={`${result.type}_${result.result_id}`}
                    result={result}
                    resultIndex={index}
                    focused={index === activeResultIndex}
                    keyboardFocused={index === keyboardResultIndex}
                />
            ))}
        </div>
    )
}

export default SearchResults
