import { useValues } from 'kea'

import { DetectiveHog } from '../hedgehogs'
import { searchBarLogic } from './searchBarLogic'
import { SearchResult, SearchResultSkeleton } from './SearchResult'
import { SearchResultPreview } from './SearchResultPreview'

export const SearchResults = (): JSX.Element => {
    const { combinedSearchResults, combinedSearchLoading, activeResultIndex, keyboardResultIndex } =
        useValues(searchBarLogic)

    return (
        <div className="SearchResults grow">
            {!combinedSearchLoading && combinedSearchResults?.length === 0 ? (
                <div className="w-full h-full flex flex-col items-center justify-center p-3">
                    <h3 className="mb-0 text-xl">No results</h3>
                    <p className="opacity-75 mb-0">This doesn't happen often, but we're stumped!</p>
                    <DetectiveHog height={150} width={150} />
                </div>
            ) : (
                <div className="overflow-hidden overscroll-contain flex h-full">
                    <div className="border-r bg-bg-3000 overscroll-contain overflow-y-scroll grow-0 shrink-0 w-80">
                        {combinedSearchLoading && (
                            <>
                                <SearchResultSkeleton />
                                <SearchResultSkeleton />
                                <SearchResultSkeleton />
                            </>
                        )}
                        {!combinedSearchLoading &&
                            combinedSearchResults?.map((result, index) => (
                                <SearchResult
                                    key={`${result.type}_${result.result_id}`}
                                    result={result}
                                    resultIndex={index}
                                    focused={index === activeResultIndex}
                                    keyboardFocused={index === keyboardResultIndex}
                                />
                            ))}
                    </div>
                    <div className="p-2 grow">
                        <SearchResultPreview />
                    </div>
                </div>
            )}
        </div>
    )
}
