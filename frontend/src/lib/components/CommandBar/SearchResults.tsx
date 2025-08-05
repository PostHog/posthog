import { useValues } from 'kea'

import { DetectiveHog } from '../hedgehogs'
import { searchBarLogic } from './searchBarLogic'
import { SearchResult, SearchResultSkeleton } from './SearchResult'
import { SearchResultPreview } from './SearchResultPreview'

export const SearchResults = (): JSX.Element => {
    const { combinedSearchResults, combinedSearchLoading, activeResultIndex } = useValues(searchBarLogic)

    return (
        <>
            {!combinedSearchLoading && combinedSearchResults?.length === 0 ? (
                <div className="w-full h-full flex flex-col items-center justify-center p-3 text-center">
                    <h3 className="mb-0 text-xl">No results</h3>
                    <p className="opacity-75 mb-0">This doesn't happen often, but we're stumped!</p>
                    <DetectiveHog height={150} width={150} />
                </div>
            ) : (
                <div className="md:grid md:grid-cols-[320px_1fr] overflow-y-auto overflow-x-hidden">
                    <div className="border-r border-b md:border-b-0 bg-background overscroll-contain overflow-y-auto overflow-x-hidden">
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
                    <div className="p-2 grow hidden md:block overflow-auto">
                        <SearchResultPreview />
                    </div>
                </div>
            )}
        </>
    )
}
