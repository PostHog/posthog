import React from 'react'
import { CommandResult as CommandResultType } from './commandPaletteLogic'
import { useEventListener } from 'lib/hooks/useEventListener'
import { useActions, useMountedLogic, useValues } from 'kea'
import { commandPaletteLogic } from './commandPaletteLogic'

interface CommandResultProps {
    result: CommandResultType
    focused?: boolean
}

function CommandResult({ result, focused }: CommandResultProps): JSX.Element {
    const { onMouseEnterResult, onMouseLeaveResult, executeResult } = useActions(commandPaletteLogic)

    const isExecutable = !!result.executor

    return (
        <div
            className={`palette_row palette__result ${focused ? 'palette__result--focused' : ''} ${
                isExecutable ? 'palette__result--executable' : ''
            }`}
            onMouseEnter={() => {
                onMouseEnterResult(result.index)
            }}
            onMouseLeave={() => {
                onMouseLeaveResult()
            }}
            onClick={() => {
                if (isExecutable) executeResult(result)
            }}
        >
            <result.icon className="palette__icon" />
            <div className="palette__display">{result.display}</div>
        </div>
    )
}

interface ResultsGroupProps {
    scope: string
    results: CommandResultType[]
    activeResultIndex: number
}

export function ResultsGroup({ scope, results, activeResultIndex }: ResultsGroupProps): JSX.Element {
    return (
        <>
            <div className="palette__row palette__row--small palette__scope">{scope}</div>
            {results.map((result) => (
                <CommandResult
                    result={result}
                    focused={result.index === activeResultIndex}
                    key={`command-result-${result.index}`}
                />
            ))}
        </>
    )
}

export function CommandResults(): JSX.Element {
    useMountedLogic(commandPaletteLogic)

    const { activeResultIndex, commandSearchResults, commandSearchResultsGrouped } = useValues(commandPaletteLogic)
    const { executeResult, onArrowUp, onArrowDown } = useActions(commandPaletteLogic)

    useEventListener('keydown', (event: KeyboardEvent) => {
        if (event.key === 'Enter' && commandSearchResults.length) {
            const result = commandSearchResults[activeResultIndex]
            const isExecutable = !!result.executor
            if (isExecutable) executeResult(result)
        } else if (event.key === 'ArrowDown') {
            onArrowDown(commandSearchResults.length - 1)
        } else if (event.key === 'ArrowUp') {
            onArrowUp()
        }
    })

    return (
        <div className="palette__results">
            {commandSearchResultsGrouped.map(([scope, results]) => (
                <ResultsGroup key={scope} scope={scope} results={results} activeResultIndex={activeResultIndex} />
            ))}
        </div>
    )
}
