import { useValues } from 'kea'

import { Command, CommandResult, CommandResultDisplayable } from '../CommandPalette/commandPaletteLogic'
import { DetectiveHog } from '../hedgehogs'

import { actionBarLogic } from './actionBarLogic'
import ActionResult from './ActionResult'
import { ResultsGroup } from 'lib/components/CommandPalette/CommandResults'
import { getNameFromActionScope } from 'lib/components/CommandBar/utils'

type ResultsGroupProps = {}

const ResultsGroup = ({ scope, results }: ResultsGroupProps): JSX.Element => {
    return (
        <>
            <div className="border-b pl-3 pr-2 pt-1 pb-1 bg-bg-3000-light">{getNameFromActionScope(scope)}</div>
            {results.map((result) => (
                <ActionResult
                    key={`command_result_${result.index}`}
                    result={result}
                    resultIndex={result.index}
                    // focused={result.index === activeResultIndex}
                />
            ))}
        </>
    )
}

const ActionResults = (): JSX.Element => {
    const { searchResults, commandSearchResultsGrouped, activeFlow } = useValues(actionBarLogic)
    console.debug('searchResults', searchResults)
    console.debug('searchResults', commandSearchResultsGrouped)

    // grouped when in flow, ungrouped otherwise

    // if (activeFlow) {
    return (
        <div className="grow overscroll-none overflow-y-auto">
            {commandSearchResultsGrouped.map(([scope, results]) => (
                <ResultsGroup
                    key={scope}
                    scope={scope}
                    results={results}
                    // activeResultIndex={activeResultIndex}
                />
            ))}
        </div>
    )
    // }

    return (
        <div className="grow overscroll-none overflow-y-auto">
            {/*        {searchResults?.length === 0 && (
                <div className="h-full flex flex-col items-center justify-center p-3">
                    <h3 className="mb-0 text-xl">No commands</h3>
                    <p className="opacity-75 mb-0">Sorry, there isn't a matching action.</p>
                    <DetectiveHog height={150} width={150} />
                </div>
            )}*/}
            {searchResults?.map((result: CommandResultDisplayable, index: number) => (
                <ActionResult
                    key={`command_result_${result.index}`}
                    result={result}
                    resultIndex={index}
                    // focused={index === activeResultIndex}
                    // keyboardFocused={index === keyboardResultIndex}
                />
            ))}
            <pre>{JSON.stringify(commandSearchResultsGrouped, null, 2)}</pre>
        </div>
    )
}

export default ActionResults
