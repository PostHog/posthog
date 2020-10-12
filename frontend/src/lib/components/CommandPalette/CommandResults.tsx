import React, { Dispatch, SetStateAction, useCallback, useState, useEffect } from 'react'
import { CommandResult as CommandResultType } from './commandLogic'
import { useEventListener } from 'lib/hooks/useEventListener'
import { useMountedLogic, useValues } from 'kea'
import { commandLogic } from './commandLogic'
import { clamp } from 'lib/utils'

interface CommandResultProps {
    result: CommandResultType
    handleSelection: (result: CommandResultType) => void
    focused?: boolean
    setHoverResultIndex: Dispatch<SetStateAction<number | undefined>>
}

function CommandResult({ result, focused, handleSelection, setHoverResultIndex }: CommandResultProps): JSX.Element {
    return (
        <div
            className={`palette_row palette__result ${focused ? 'palette__result--focused' : ''}`}
            onMouseEnter={() => {
                setHoverResultIndex(result.index)
            }}
            onMouseLeave={() => {
                setHoverResultIndex(undefined)
            }}
            onClick={() => {
                handleSelection(result)
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
    handleCommandSelection: (result: CommandResultType) => void
    setHoverResultIndex: Dispatch<SetStateAction<number | undefined>>
    actuallyActiveResultIndex: number
}

export function ResultsGroup({
    scope,
    results,
    handleCommandSelection,
    setHoverResultIndex,
    actuallyActiveResultIndex,
}: ResultsGroupProps): JSX.Element {
    return (
        <>
            <div className="palette__row palette__row--small palette__scope">{scope}</div>
            {results.map((result) => (
                <CommandResult
                    result={result}
                    focused={result.index === actuallyActiveResultIndex}
                    key={`command-result-${result.index}`}
                    handleSelection={handleCommandSelection}
                    setHoverResultIndex={setHoverResultIndex}
                />
            ))}
        </>
    )
}

interface CommandResultsProps {
    handleCommandSelection: (result: CommandResultType) => void
}

export function CommandResults({ handleCommandSelection }: CommandResultsProps): JSX.Element {
    useMountedLogic(commandLogic)

    const { searchInput, isPaletteShown, commandSearchResults, commandSearchResultsGrouped } = useValues(commandLogic)

    const [activeResultIndex, setActiveResultIndex] = useState(0)
    const [hoverResultIndex, setHoverResultIndex] = useState<number | undefined>()

    const actuallyActiveResultIndex =
        hoverResultIndex ??
        (commandSearchResults.length ? clamp(activeResultIndex, 0, commandSearchResults.length - 1) : 0)

    const handleEnterDown = useCallback(
        (event: KeyboardEvent) => {
            if (event.key === 'Enter' && commandSearchResults.length) {
                handleCommandSelection(commandSearchResults[actuallyActiveResultIndex])
            }
        },
        [actuallyActiveResultIndex, commandSearchResults]
    )

    useEventListener('keydown', handleEnterDown)

    useEffect(() => {
        setHoverResultIndex(undefined)
        setActiveResultIndex(0)
    }, [isPaletteShown, searchInput])

    const handleKeyDown = useCallback(
        (event: KeyboardEvent) => {
            if (isPaletteShown) {
                if (event.key === 'ArrowDown') {
                    setActiveResultIndex(Math.min(actuallyActiveResultIndex + 1, commandSearchResults.length - 1))
                    setHoverResultIndex(undefined)
                } else if (event.key === 'ArrowUp') {
                    setActiveResultIndex(Math.max(actuallyActiveResultIndex - 1, 0))
                    setHoverResultIndex(undefined)
                }
            }
        },
        [
            setActiveResultIndex,
            setHoverResultIndex,
            hoverResultIndex,
            activeResultIndex,
            commandSearchResults,
            isPaletteShown,
        ]
    )

    useEventListener('keydown', handleKeyDown)

    return (
        <div>
            {commandSearchResultsGrouped.map(([scope, results]) => (
                <ResultsGroup
                    key={scope}
                    scope={scope}
                    results={results}
                    handleCommandSelection={handleCommandSelection}
                    setHoverResultIndex={setHoverResultIndex}
                    actuallyActiveResultIndex={actuallyActiveResultIndex}
                />
            ))}
        </div>
    )
}
