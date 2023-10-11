import { useValues } from 'kea'

import { searchBarLogic } from './searchBarLogic'
import SearchResult from './SearchResult'

const SearchResults = (): JSX.Element => {
    const { searchResponse, activeResultIndex } = useValues(searchBarLogic)
    return (
        <div className="grow">
            {searchResponse?.results.map((result) => (
                <SearchResult
                    key={`${result.type}_${result.pk}`}
                    result={result}
                    // focused={result.index === activeResultIndex}
                />
            ))}
        </div>
    )
}

export default SearchResults
