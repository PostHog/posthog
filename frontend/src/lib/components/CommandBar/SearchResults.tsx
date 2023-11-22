import { useValues } from 'kea'

import { DetectiveHog } from '../hedgehogs'
import { searchBarLogic } from './searchBarLogic'
import { SearchResult, SearchResultSkeleton } from './SearchResult'
import { SearchResultPreview } from './SearchResultPreview'

export const SearchResults = (): JSX.Element => {
    const { filterSearchResults, searchResponseLoading, activeResultIndex, keyboardResultIndex } =
        useValues(searchBarLogic)

    return (
        <div className="flex grow overflow-hidden">
            <div className="w-1/2 overscroll-none overflow-y-auto border-r bg-bg-light">
                {searchResponseLoading && (
                    <>
                        <SearchResultSkeleton />
                        <SearchResultSkeleton />
                        <SearchResultSkeleton />
                    </>
                )}
                {!searchResponseLoading && filterSearchResults?.length === 0 && (
                    <div className="h-full flex flex-col items-center justify-center p-3">
                        <h3 className="mb-0 text-xl">No results</h3>
                        <p className="opacity-75 mb-0">This doesn't happen often, but we're stumped!</p>
                        <DetectiveHog height={150} width={150} />
                    </div>
                )}
                {!searchResponseLoading &&
                    filterSearchResults?.map((result, index) => (
                        <SearchResult
                            key={`${result.type}_${result.result_id}`}
                            result={result}
                            resultIndex={index}
                            focused={index === activeResultIndex}
                            keyboardFocused={index === keyboardResultIndex}
                        />
                    ))}
            </div>
            <div className="w-1/2 p-2">
                <SearchResultPreview />
            </div>
        </div>
    )
}
