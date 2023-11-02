import { useActions, useValues } from 'kea'
import { useEventListener } from 'lib/hooks/useEventListener'
import { Command, CommandResult, CommandResultDisplayable } from '../CommandPalette/commandPaletteLogic'
import { DetectiveHog } from '../hedgehogs'
import { actionBarLogic } from './actionBarLogic'
import ActionResult from './ActionResult'

import { searchBarLogic } from './searchBarLogic'
import SearchResult, { SearchResultSkeleton } from './SearchResult'

const ActionResults = (): JSX.Element => {
    // const { activeResultIndex, keyboardResultIndex, maxIndex } =
    //     useValues(searchBarLogic)
    // const { onArrowUp, onArrowDown, openResult } = useActions(searchBarLogic)
    const { searchResults } = useValues(actionBarLogic)

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

    return (
        <div className="grow overscroll-none overflow-y-auto">
            {searchResults?.length === 0 && (
                <div className="h-full flex flex-col items-center justify-center p-3">
                    <h3 className="mb-0 text-xl">No commands</h3>
                    <p className="opacity-75 mb-0">Sorry, there isn't a matching action.</p>
                    <DetectiveHog height={150} width={150} />
                </div>
            )}
            {searchResults?.map((result: CommandResultDisplayable, index: number) => (
                <ActionResult
                    key={`command_result_${result.index}`}
                    result={result}
                    resultIndex={index}
                    // focused={index === activeResultIndex}
                    // keyboardFocused={index === keyboardResultIndex}
                />
            ))}
        </div>
    )
}

export default ActionResults
