import React, { useEffect, useState, useRef } from 'react'
import { useOutsideClickHandler } from 'lib/utils'
import { useHotkeys } from 'react-hotkeys-hook'
import { useMountedLogic, useValues, useActions } from 'kea'
import { CommandResult as CommandResultType, commandLogic } from './commandLogic'
import { CommandInput } from './CommandInput'
import { CommandResult } from './CommandResult'
import styled from 'styled-components'
import { userLogic } from 'scenes/userLogic'
import { useEventListener } from 'lib/hooks/useEventListener'
import { useCallback } from 'react'

const CommandPaletteContainer = styled.div`
    position: absolute;
    top: 0;
    left: 0;
    width: 100%;
    height: 100%;
    display: flex;
    flex-direction: column;
    align-items: center;
`

const CommandPaletteBox = styled.div`
    position: fixed;
    top: 30%;
    display: flex;
    flex-direction: column;
    z-index: 9999;
    width: 32rem;
    max-height: 60%;
    overflow: hidden;
`

/*const Scope = styled.div`
    background-color: #4d4d4d;
    height: 22px;
    width: 100%;
    padding-left: 16px;
    padding-right: 16px;
    text-transform: uppercase;
    color: rgba(255, 255, 255, 0.8);
    font-weight: bold;
`*/

const ResultsContainer = styled.div`
    border-top: 1px solid rgba(0, 0, 0, 0.35);
    overflow-y: scroll;
`

export function CommandPalette(): JSX.Element | null {
    useMountedLogic(commandLogic)

    const { setSearchInput: setInput } = useActions(commandLogic)
    const { searchInput: input, commandSearchResults } = useValues(commandLogic)
    const boxRef = useRef<HTMLDivElement | null>(null)
    const [isPaletteShown, setIsPaletteShown] = useState(false)
    const { user } = useValues(userLogic)

    const handleCommandSelection = (result: CommandResultType): void => {
        // Called after a command is selected by the user
        result.executor()
        setIsPaletteShown(false)
        setInput('')
    }
    const [activeResultIndex, setActiveResultIndex] = useState(0)

    const toggleIsPaletteShown = useCallback(() => {
        setIsPaletteShown(!isPaletteShown)
    }, [setIsPaletteShown, isPaletteShown])

    useHotkeys('cmd+k,ctrl+k', toggleIsPaletteShown)

    useHotkeys('esc', () => {
        setIsPaletteShown(false)
    })

    useOutsideClickHandler(boxRef, () => {
        setIsPaletteShown(false)
    })

    useEffect(() => {
        // prevent scrolling when box is open
        document.body.style.overflow = isPaletteShown ? 'hidden' : ''
        setActiveResultIndex(0)
    }, [isPaletteShown])

    useEffect(() => {
        setActiveResultIndex(0)
    }, [input])

    const _handleKeyDown = useCallback(
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
        [input, isPaletteShown]
    )

    useEventListener('keydown', _handleKeyDown)

    const _handleEnterDown = useCallback(
        (e: KeyboardEvent) => {
            if (e.key === 'Enter') {
                handleCommandSelection(commandSearchResults[activeResultIndex])
            }
        },
        [activeResultIndex, input]
    )

    useEventListener('keydown', _handleEnterDown)

    return (
        <>
            {!user || !isPaletteShown ? null : (
                <CommandPaletteContainer>
                    <CommandPaletteBox ref={boxRef} className="card bg-dark">
                        <CommandInput setIsPaletteShown={setIsPaletteShown} input={input} setInput={setInput} />
                        {commandSearchResults && (
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
                        )}
                    </CommandPaletteBox>
                </CommandPaletteContainer>
            )}
        </>
    )
}
