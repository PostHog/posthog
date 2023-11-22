import { useValues } from 'kea'
import { getNameFromActionScope } from 'lib/components/CommandBar/utils'

import { CommandResultDisplayable } from '../CommandPalette/commandPaletteLogic'
import { actionBarLogic } from './actionBarLogic'
import { ActionResult } from './ActionResult'

type ResultsGroupProps = {
    scope: string
    results: CommandResultDisplayable[]
    activeResultIndex: number
}

const ResultsGroup = ({ scope, results, activeResultIndex }: ResultsGroupProps): JSX.Element => {
    return (
        <>
            <div className="border-b pl-3 pr-2 pt-1 pb-1 bg-bg-3000 text-xs font-bold text-muted-3000 uppercase">
                {getNameFromActionScope(scope)}
            </div>
            {results.map((result) => (
                <ActionResult
                    key={`command_result_${result.index}`}
                    result={result}
                    focused={result.index === activeResultIndex}
                />
            ))}
        </>
    )
}

export const ActionResults = (): JSX.Element => {
    const { commandSearchResultsGrouped, activeResultIndex } = useValues(actionBarLogic)

    return (
        <div className="grow overscroll-none overflow-y-auto">
            {commandSearchResultsGrouped.map(([scope, results]) => (
                <ResultsGroup key={scope} scope={scope} results={results} activeResultIndex={activeResultIndex} />
            ))}
        </div>
    )
}
