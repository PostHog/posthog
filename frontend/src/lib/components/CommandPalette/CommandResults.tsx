import React, { Dispatch, SetStateAction, useCallback, useState, useEffect } from 'react'
import styled from 'styled-components'
import { CommandExecutor, CommandResult as CommandResultType } from './commandLogic'
import { useEventListener } from 'lib/hooks/useEventListener'
import { useMountedLogic, useValues } from 'kea'
import { commandLogic } from './commandLogic'
import { clamp } from 'lib/utils'

interface ContainerProps {
    focused?: boolean
    isHint?: boolean
    onClick?: CommandExecutor
}

const ResultDiv = styled.div<ContainerProps>`
    height: 4rem;
    width: 100%;
    padding: 0 2rem;
    display: flex;
    align-items: center;
    color: rgba(255, 255, 255, 0.95);
    font-size: 1rem;
    position: relative;
    cursor: pointer;

    ${({ focused }) =>
        focused &&
        `
        background-color: rgba(0, 0, 0, 0.35);

        &:before {
            background-color: #1890ff; 
            content: '';
            position: absolute;
            left: 0;
            top: 0;
            bottom: 0;
            width: 0.375rem;
        }
        `}
    ${({ isHint }) =>
        isHint &&
        `
        color: rgba(255, 255, 255, 0.7) !important;  
        cursor: default !important;
    `};
    }
`

const Scope = styled.div`
    height: 1.5rem;
    line-height: 1.5rem;
    width: 100%;
    padding: 0 2rem;
    background-color: rgba(255, 255, 255, 0.1);
    color: rgba(255, 255, 255, 0.8);
    font-size: 0.75rem;
    text-transform: uppercase;
    font-weight: bold;
`

const ResultsContainer = styled.div`
    overflow-y: scroll;
`

const ResultDisplay = styled.span`
    padding-left: 1rem;
`

interface CommandResultProps {
    result: CommandResultType
    handleSelection: (result: CommandResultType) => void
    focused?: boolean
    isHint?: boolean
    setHoverResultIndex: Dispatch<SetStateAction<number | null>>
}

function CommandResult({
    result,
    focused,
    isHint,
    handleSelection,
    setHoverResultIndex,
}: CommandResultProps): JSX.Element {
    return (
        <ResultDiv
            onMouseEnter={() => {
                setHoverResultIndex(result.index)
            }}
            onMouseLeave={() => {
                setHoverResultIndex(null)
            }}
            focused={focused}
            isHint={isHint}
            onClick={() => {
                handleSelection(result.index)
            }}
        >
            <result.icon />
            <ResultDisplay>{result.display}</ResultDisplay>
        </ResultDiv>
    )
}

interface ResultsGroupProps {
    scope: string
    results: CommandResultType[]
    handleCommandSelection: (result: CommandResultType) => void
    setHoverResultIndex: Dispatch<SetStateAction<number | null>>
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
    setIsPaletteShown: Dispatch<SetStateAction<boolean>>
    isPaletteShown: boolean
    setInput: (input: string) => void
}

export function CommandResults({ setIsPaletteShown, isPaletteShown, setInput }: CommandResultsProps): JSX.Element {
    useMountedLogic(commandLogic)

    const { commandSearchResults, searchInput } = useValues(commandLogic)

    const [activeResultIndex, setActiveResultIndex] = useState(0)
    const [hoverResultIndex, setHoverResultIndex] = useState<number | null>(null)

    const actuallyActiveResultIndex =
        hoverResultIndex || (commandSearchResults.length ? clamp(activeResultIndex, 0, commandSearchResults.length) : 0)

    const handleCommandSelection = useCallback(
        (result: CommandResultType) => {
            // Called after a command is selected by the user
            result.executor()
            setIsPaletteShown(false)
            setInput('')
        },
        [setIsPaletteShown, setInput]
    )

    const handleEnterDown = useCallback(
        (event: KeyboardEvent) => {
            if (event.key === 'Enter') {
                handleCommandSelection(commandSearchResults[actuallyActiveResultIndex])
            }
        },
        [actuallyActiveResultIndex, commandSearchResults]
    )

    useEventListener('keydown', handleEnterDown)

    useEffect(() => {
        setActiveResultIndex(0)
    }, [searchInput, isPaletteShown])

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
    const sortedGroups = Object.entries(groupedResults).sort(([scopeA]) => (scopeA === 'global' ? 1 : -1))
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
