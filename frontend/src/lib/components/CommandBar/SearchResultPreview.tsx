import { useValues } from 'kea'
import { ResultDescription, ResultName } from 'lib/components/CommandBar/SearchResult'

import { resultTypeToName } from './constants'
import { searchBarLogic } from './searchBarLogic'

export const SearchResultPreview = (): JSX.Element | null => {
    const { activeResultIndex, filterSearchResults } = useValues(searchBarLogic)

    if (!filterSearchResults || filterSearchResults.length === 0) {
        return null
    }

    const result = filterSearchResults[activeResultIndex]

    return (
        <div className="border bg-bg-light rounded p-6">
            <div>{resultTypeToName[result.type]}</div>
            <div className="text-text-3000 font-bold text-lg">
                <ResultName result={result} />
            </div>
            <div className="mt-2 text-muted">
                <ResultDescription result={result} />
            </div>
        </div>
    )
}
