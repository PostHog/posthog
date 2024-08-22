import clsx from 'clsx'
import { useValues } from 'kea'
import { useResizeBreakpoints } from 'lib/hooks/useResizeObserver'

import { DetectiveHog } from '../hedgehogs'
import { searchBarLogic } from './searchBarLogic'
import { SearchResult, SearchResultSkeleton } from './SearchResult'
import { SearchResultPreview } from './SearchResultPreview'

export const SearchResults = (): JSX.Element => {
    const { combinedSearchResults, combinedSearchLoading, activeResultIndex } = useValues(searchBarLogic)

    const { ref, size } = useResizeBreakpoints({
        0: 'small',
        550: 'normal',
    })

    return (
        <div className="SearchResults grow" ref={ref}>
            {!combinedSearchLoading && combinedSearchResults?.length === 0 ? (
                <div className="w-full h-full flex flex-col items-center justify-center p-3">
                    <h3 className="mb-0 text-xl">No results</h3>
                    <p className="opacity-75 mb-0">This doesn't happen often, but we're stumped!</p>
                    <DetectiveHog height={150} width={150} />
                </div>
            ) : (
                <div className="overflow-hidden overscroll-contain flex h-full">
                    <div
                        className={clsx(
                            'border-r bg-bg-3000 overscroll-contain overflow-y-scroll grow-0 shrink-0 w-full',
                            size !== 'small' && 'max-w-80'
                        )}
                    >
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
                    {size !== 'small' ? (
                        <div className="p-2 grow">
                            <SearchResultPreview />
                        </div>
                    ) : null}
                </div>
            )}
        </div>
    )
}
