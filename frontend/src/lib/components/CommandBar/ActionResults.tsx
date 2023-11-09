import { useValues } from 'kea'

import { Command, CommandResult, CommandResultDisplayable } from '../CommandPalette/commandPaletteLogic'
import { DetectiveHog } from '../hedgehogs'

import { actionBarLogic } from './actionBarLogic'
import ActionResult from './ActionResult'

const ActionResults = (): JSX.Element => {
    const { searchResults } = useValues(actionBarLogic)
    console.debug('searchResults', searchResults)

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
