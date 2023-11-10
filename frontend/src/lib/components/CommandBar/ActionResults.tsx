import { useValues } from 'kea'

import { Command, CommandResult, CommandResultDisplayable } from '../CommandPalette/commandPaletteLogic'
import { DetectiveHog } from '../hedgehogs'

import { actionBarLogic } from './actionBarLogic'
import ActionResult from './ActionResult'
import { ResultsGroup } from 'lib/components/CommandPalette/CommandResults'
import { getNameFromActionScope } from 'lib/components/CommandBar/utils'
import { useEventListener } from 'lib/hooks/useEventListener'

type ResultsGroupProps = {
    scope: string
    results: CommandResultDisplayable[]
    activeResultIndex: number
}

const ResultsGroup = ({ scope, results, activeResultIndex }: ResultsGroupProps): JSX.Element => {
    return (
        <>
            <div className="border-b pl-3 pr-2 pt-1 pb-1 bg-bg-3000-light">{getNameFromActionScope(scope)}</div>
            {results.map((result) => (
                <ActionResult
                    key={`command_result_${result.index}`}
                    result={result}
                    resultIndex={result.index}
                    focused={result.index === activeResultIndex}
                />
            ))}
        </>
    )
}

const ActionResults = (): JSX.Element => {
    const { commandSearchResultsGrouped, activeResultIndex } = useValues(actionBarLogic)

    return (
        <div className="grow overscroll-none overflow-y-auto">
            {commandSearchResultsGrouped.map(([scope, results]) => (
                <ResultsGroup key={scope} scope={scope} results={results} activeResultIndex={activeResultIndex} />
            ))}
        </div>
    )
}

export default ActionResults
