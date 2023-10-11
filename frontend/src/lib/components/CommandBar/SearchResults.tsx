import { useActions, useValues } from 'kea'
import { useEventListener } from 'lib/hooks/useEventListener'

import { searchBarLogic } from './searchBarLogic'
import SearchResult from './SearchResult'

const SearchResults = (): JSX.Element => {
    const { searchResults, activeResultIndex } = useValues(searchBarLogic)
    const { onArrowUp, onArrowDown } = useActions(searchBarLogic)

    useEventListener('keydown', (event) => {
        if (event.key === 'Enter') {
            // const result = commandSearchResults[activeResultIndex]
            // // const isExecutable = !!result.executor
            // // if (isExecutable) {
            // //     executeResult(result)
            // // }
        } else if (event.key === 'ArrowDown') {
            event.preventDefault()
            onArrowDown()
        } else if (event.key === 'ArrowUp') {
            event.preventDefault()
            onArrowUp()
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
                />
            ))}
        </div>
    )
}

export default SearchResults
