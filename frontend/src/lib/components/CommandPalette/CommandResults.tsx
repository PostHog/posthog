import React, { Dispatch, SetStateAction, useCallback, useState, useEffect } from 'react'
import styled from 'styled-components'
import { CommandExecutor, CommandResult as CommandResultType } from './commandLogic'
import { useEventListener } from 'lib/hooks/useEventListener'
import { useMountedLogic, useValues } from 'kea'
import { commandLogic } from './commandLogic'

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

const ResultsContainer = styled.div`
    border-top: 1px solid rgba(0, 0, 0, 0.5);
    overflow-y: scroll;
`

const IconContainer = styled.span`
    margin-right: 1rem;
`

interface CommandResultProps {
    result: CommandResultType
    handleSelection: (result: CommandResultType) => void
    focused?: boolean
    isHint?: boolean
    onMouseOver?: (e: MouseEvent) => void
}

function CommandResult({ result, focused, isHint, handleSelection, onMouseOver }: CommandResultProps): JSX.Element {
    return (
        <ResultDiv
            onMouseOver={onMouseOver}
            focused={focused}
            isHint={isHint}
            onClick={() => {
                handleSelection(result)
            }}
        >
            <IconContainer>
                <result.icon />
            </IconContainer>
            {result.display}
        </ResultDiv>
    )
}

interface CommandResultsProps {
    setIsPaletteShown: Dispatch<SetStateAction<boolean>>
    isPaletteShown: boolean
    setInput: (input: string) => void
}

export function CommandResults({ setIsPaletteShown, isPaletteShown, setInput }: CommandResultsProps): JSX.Element {
    useMountedLogic(commandLogic)

    const { commandSearchResults } = useValues(commandLogic)

    const [activeResultIndex, setActiveResultIndex] = useState(0)

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
                handleCommandSelection(commandSearchResults[activeResultIndex])
            }
        },
        [activeResultIndex]
    )

    useEventListener('keydown', handleEnterDown)

    useEffect(() => {
        // prevent scrolling when box is open
        document.body.style.overflow = isPaletteShown ? 'hidden' : ''
        setActiveResultIndex(0)
    }, [isPaletteShown])

    useEffect(() => {
        if (commandSearchResults.length - 1 > activeResultIndex) {
            setActiveResultIndex(0)
        }
    }, [CommandResult])

    const handleKeyDown = useCallback(
        (e: KeyboardEvent) => {
            if (isPaletteShown) {
                if (e.key === 'ArrowDown') {
                    setActiveResultIndex((prevIndex) => {
                        if (prevIndex === commandSearchResults.length - 1) return prevIndex
                        else return prevIndex + 1
                    })
                } else if (e.key === 'ArrowUp') {
                    setActiveResultIndex((prevIndex) => {
                        if (prevIndex === 0) return prevIndex
                        else return prevIndex - 1
                    })
                }
            }
        },
        [commandSearchResults, isPaletteShown]
    )

    useEventListener('keydown', handleKeyDown)

    return (
        <ResultsContainer>
            {commandSearchResults.map((result, index) => (
                <CommandResult
                    focused={activeResultIndex === index}
                    key={`command-result-${index}`}
                    result={result}
                    handleSelection={handleCommandSelection}
                    onMouseOver={() => {
                        setActiveResultIndex(-1)
                    }}
                    onMouseOut={() => {
                        setActiveResultIndex(0)
                    }}
                />
            ))}
        </ResultsContainer>
    )
}
