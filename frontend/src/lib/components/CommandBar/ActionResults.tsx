import { useValues } from 'kea'

import { getNameFromActionScope } from 'lib/components/CommandBar/utils'

import { CommandResultDisplayable } from '../CommandPalette/commandPaletteLogic'
import { ActionResult } from './ActionResult'
import { actionBarLogic } from './actionBarLogic'

type ResultsGroupProps = {
    scope: string
    results: CommandResultDisplayable[]
    activeResultIndex: number
}

const ResultsGroup = ({ scope, results, activeResultIndex }: ResultsGroupProps): JSX.Element => {
    return (
        <>
            <div className="bg-primary text-secondary border-b px-5 pb-1 pt-1 text-xs font-bold uppercase">
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
        <div className="grow overflow-y-auto overscroll-none">
            {commandSearchResultsGrouped.map(([scope, results]) => (
                <ResultsGroup key={scope} scope={scope} results={results} activeResultIndex={activeResultIndex} />
            ))}
        </div>
    )
}
