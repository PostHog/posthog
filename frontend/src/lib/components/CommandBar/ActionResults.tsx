import { useActions, useValues } from 'kea'
import { useEventListener } from 'lib/hooks/useEventListener'
import { Command, CommandResult, CommandResultDisplayable } from '../CommandPalette/commandPaletteLogic'
import { DetectiveHog } from '../hedgehogs'
import { actionBarLogic } from './actionBarLogic'

import { searchBarLogic } from './searchBarLogic'
import SearchResult, { SearchResultSkeleton } from './SearchResult'

const ActionResults = (): JSX.Element => {
    // const { filterSearchResults, searchResponseLoading, activeResultIndex, keyboardResultIndex, maxIndex } =
    //     useValues(searchBarLogic)
    // const { onArrowUp, onArrowDown, openResult } = useActions(searchBarLogic)
    const { searchResults } = useValues(actionBarLogic)
    return (
        <>
            {searchResults.map((command: CommandResultDisplayable) => (
                <div key={command.index} className="flex">
                    <command.icon className="" />
                    <div className="">{command.display}</div>
                </div>
            ))}
        </>
    )

    // useEventListener('keydown', (event) => {
    //     if (!filterSearchResults) {
    //         return
    //     }

    //     if (event.key === 'Enter') {
    //         event.preventDefault()
    //         openResult(activeResultIndex)
    //     } else if (event.key === 'ArrowDown') {
    //         event.preventDefault()
    //         onArrowDown(activeResultIndex, maxIndex)
    //     } else if (event.key === 'ArrowUp') {
    //         event.preventDefault()
    //         onArrowUp(activeResultIndex, maxIndex)
    //     }
    // })

    // return (
    //     <div className="grow overscroll-none overflow-y-auto">
    //         {searchResponseLoading && (
    //             <>
    //                 <SearchResultSkeleton />
    //                 <SearchResultSkeleton />
    //                 <SearchResultSkeleton />
    //             </>
    //         )}
    //         {!searchResponseLoading && filterSearchResults?.length === 0 && (
    //             <div className="h-full flex flex-col items-center justify-center p-3">
    //                 <h3 className="mb-0 text-xl">No results</h3>
    //                 <p className="opacity-75 mb-0">This doesn't happen often, but we're stumped!</p>
    //                 <DetectiveHog height={150} width={150} />
    //             </div>
    //         )}
    //         {!searchResponseLoading &&
    //             filterSearchResults?.map((result, index) => (
    //                 <SearchResult
    //                     key={`${result.type}_${result.result_id}`}
    //                     result={result}
    //                     resultIndex={index}
    //                     focused={index === activeResultIndex}
    //                     keyboardFocused={index === keyboardResultIndex}
    //                 />
    //             ))}
    //     </div>
    // )
}

export default ActionResults
