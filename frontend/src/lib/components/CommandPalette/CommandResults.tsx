import React, { useEffect, useRef } from 'react'
import { CommandResultDisplayable } from './commandPaletteLogic'
import { useEventListener } from 'lib/hooks/useEventListener'
import { useActions, useMountedLogic, useValues } from 'kea'
import { commandPaletteLogic } from './commandPaletteLogic'

interface CommandResultProps {
    result: CommandResultDisplayable
    focused?: boolean
}

function CommandResult({ result, focused }: CommandResultProps): JSX.Element {
    const { onMouseEnterResult, onMouseLeaveResult, executeResult } = useActions(commandPaletteLogic)

    const ref = useRef<HTMLDivElement | null>(null)

    const isExecutable = !!result.executor
    useEffect(() => {
        if (focused) {
            ref.current?.scrollIntoView()
        }
    }, [focused])

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
                if (isExecutable) {
                    executeResult(result)
                }
            }}
            title={result.display}
            ref={ref}
        >
            <result.icon className="palette__icon" />
            <div className="palette__display">{result.display}</div>
        </div>
    )
}

interface ResultsGroupProps {
    scope: string
    results: CommandResultDisplayable[]
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

    useEventListener('keydown', (event) => {
        if (event.key === 'Enter' && commandSearchResults.length) {
            const result = commandSearchResults[activeResultIndex]
            const isExecutable = !!result.executor
            if (isExecutable) {
                executeResult(result)
            }
        } else if (event.key === 'ArrowDown') {
            event.preventDefault()
            onArrowDown(commandSearchResults.length - 1)
        } else if (event.key === 'ArrowUp') {
            event.preventDefault()
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
