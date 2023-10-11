import { useActions, useValues } from 'kea'
import { useEventListener } from 'lib/hooks/useEventListener'

import { searchBarLogic } from './searchBarLogic'
import SearchResult from './SearchResult'

const SearchResults = (): JSX.Element => {
    const { searchResults, activeResultIndex, keyboardResultIndex, maxIndex } = useValues(searchBarLogic)
    const { onArrowUp, onArrowDown } = useActions(searchBarLogic)

    useEventListener('keydown', (event) => {
        if (!searchResults) {
            return
        }

        if (event.key === 'Enter') {
            // const result = commandSearchResults[activeResultIndex]
            // // const isExecutable = !!result.executor
            // // if (isExecutable) {
            // //     executeResult(result)
            // // }
        } else if (event.key === 'ArrowDown') {
            event.preventDefault()
            onArrowDown(activeResultIndex, maxIndex)
        } else if (event.key === 'ArrowUp') {
            event.preventDefault()
            onArrowUp(activeResultIndex)
        }
    })

    return (
        <div className="grow overscroll-none overflow-y-auto">
            {searchResults?.map((result, index) => (
                <SearchResult
                    key={`${result.type}_${result.pk}`}
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
