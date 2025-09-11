import { useValues } from 'kea'

import { DetectiveHog } from '../hedgehogs'
import { SearchResult, SearchResultSkeleton } from './SearchResult'
import { SearchResultPreview } from './SearchResultPreview'
import { searchBarLogic } from './searchBarLogic'

export const SearchResults = (): JSX.Element => {
    const { combinedSearchResults, combinedSearchLoading, anySearchLoading, activeResultIndex } =
        useValues(searchBarLogic)

    return (
        <>
            {!combinedSearchLoading && !anySearchLoading && combinedSearchResults?.length === 0 ? (
                <div className="w-full h-full flex flex-col items-center justify-center p-3 text-center">
                    <h3 className="mb-0 text-xl">No results</h3>
                    <p className="opacity-75 mb-0">This doesn't happen often, but we're stumped!</p>
                    <DetectiveHog height={150} width={150} />
                </div>
            ) : (
                <div className="md:grid md:grid-cols-[320px_1fr] overflow-y-auto overflow-x-hidden">
                    <div className="border-r border-b md:border-b-0 bg-primary overscroll-contain overflow-y-auto overflow-x-hidden">
                        {combinedSearchLoading && !combinedSearchResults?.length && (
                            <>
                                <SearchResultSkeleton />
                                <SearchResultSkeleton />
                                <SearchResultSkeleton />
                            </>
                        )}
                        {combinedSearchResults?.map((result, index) => (
                            <SearchResult
                                key={`${result.type}_${result.result_id}`}
                                result={result}
                                resultIndex={index}
                                focused={index === activeResultIndex}
                            />
                        ))}
                        {!combinedSearchLoading && anySearchLoading && (
                            <div className="px-3 py-2 text-xs text-muted opacity-75 border-t">
                                Loading more results...
                            </div>
                        )}
                    </div>
                    <div className="p-2 grow hidden md:block overflow-auto">
                        <SearchResultPreview />
                    </div>
                </div>
            )}
        </>
    )
}
