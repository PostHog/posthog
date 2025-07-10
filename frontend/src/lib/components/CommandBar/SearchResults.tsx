import { useValues } from 'kea'

import { DetectiveHog } from '../hedgehogs'
import { SearchResult, SearchResultSkeleton } from './SearchResult'
import { SearchResultPreview } from './SearchResultPreview'
import { searchBarLogic } from './searchBarLogic'

export const SearchResults = (): JSX.Element => {
    const { combinedSearchResults, combinedSearchLoading, activeResultIndex } = useValues(searchBarLogic)

    return (
        <>
            {!combinedSearchLoading && combinedSearchResults?.length === 0 ? (
                <div className="flex h-full w-full flex-col items-center justify-center p-3 text-center">
                    <h3 className="mb-0 text-xl">No results</h3>
                    <p className="mb-0 opacity-75">This doesn't happen often, but we're stumped!</p>
                    <DetectiveHog height={150} width={150} />
                </div>
            ) : (
                <div className="overflow-y-auto overflow-x-hidden md:grid md:grid-cols-[320px_1fr]">
                    <div className="bg-primary overflow-y-auto overflow-x-hidden overscroll-contain border-b border-r md:border-b-0">
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
                                />
                            ))}
                    </div>
                    <div className="hidden grow overflow-auto p-2 md:block">
                        <SearchResultPreview />
                    </div>
                </div>
            )}
        </>
    )
}
