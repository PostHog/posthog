import React, { Dispatch, SetStateAction, useCallback, useState, useEffect } from 'react'
import { CommandResult as CommandResultType } from './commandLogic'
import { useEventListener } from 'lib/hooks/useEventListener'
import { useMountedLogic, useValues } from 'kea'
import { commandLogic } from './commandLogic'
import { ResultsContainer, Scope, ResultBox, ResultIconContainer, ResultDisplay } from './commandStyledComponents'
import { clamp } from 'lib/utils'

interface CommandResultProps {
    result: CommandResultType
    handleSelection: (result: CommandResultType) => void
    focused?: boolean
    setHoverResultIndex: Dispatch<SetStateAction<number | undefined | null>>
}

function CommandResult({ result, focused, handleSelection, setHoverResultIndex }: CommandResultProps): JSX.Element {
    return (
        <ResultBox
            onMouseEnter={() => {
                setHoverResultIndex(result.index)
            }}
            onMouseLeave={() => {
                setHoverResultIndex(null)
            }}
            focused={focused}
            onClick={() => {
                handleSelection(result)
            }}
        >
            <ResultIconContainer>
                <result.icon />
            </ResultIconContainer>
            <ResultDisplay>{result.display}</ResultDisplay>
        </ResultBox>
    )
}

interface ResultsGroupProps {
    scope: string
    results: CommandResultType[]
    handleCommandSelection: (result: CommandResultType) => void
    setHoverResultIndex: Dispatch<SetStateAction<number | null | undefined>>
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
            <Scope>{scope}</Scope>
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

    const { isPaletteShown, commandSearchResults } = useValues(commandLogic)

    const [activeResultIndex, setActiveResultIndex] = useState(0)
    const [hoverResultIndex, setHoverResultIndex] = useState<number | null | undefined>(null)

    const actuallyActiveResultIndex =
        hoverResultIndex || (commandSearchResults.length ? clamp(activeResultIndex, 0, commandSearchResults.length) : 0)

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
        setActiveResultIndex(0)
    }, [isPaletteShown])

    const handleKeyDown = useCallback(
        (event: KeyboardEvent) => {
            if (isPaletteShown) {
                if (event.key === 'ArrowDown') {
                    setActiveResultIndex(Math.min(actuallyActiveResultIndex + 1, commandSearchResults.length - 1))
                    setHoverResultIndex(null)
                } else if (event.key === 'ArrowUp') {
                    setActiveResultIndex(Math.max(actuallyActiveResultIndex - 1, 0))
                    setHoverResultIndex(null)
                }
            }
        },
        [setActiveResultIndex, setHoverResultIndex, actuallyActiveResultIndex, commandSearchResults, isPaletteShown]
    )

    useEventListener('keydown', handleKeyDown)

    const groupedResults: { [scope: string]: CommandResultType[] } = {}
    for (const result of commandSearchResults) {
        const scope: string = result.command.scope
        if (!(scope in groupedResults)) groupedResults[scope] = []
        groupedResults[scope].push(result)
    }
    // Always put global commands group last
    const sortedGroups = Object.entries(groupedResults)
    let rollingIndex = 0
    for (const [, group] of sortedGroups) {
        for (const result of group) {
            result.index = rollingIndex++
        }
    }

    return (
        <ResultsContainer>
            {sortedGroups.map(([scope, results]) => (
                <ResultsGroup
                    key={scope}
                    scope={scope}
                    results={results}
                    handleCommandSelection={handleCommandSelection}
                    setHoverResultIndex={setHoverResultIndex}
                    actuallyActiveResultIndex={actuallyActiveResultIndex}
                />
            ))}
        </ResultsContainer>
    )
}
