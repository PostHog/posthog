import React, { useEffect, useState } from 'react'
import { useOutsideClickHandler } from 'lib/utils'
import { useRef } from 'react'
import { useActions } from 'kea'
import { router } from 'kea-router'
import { useHotkeys } from 'react-hotkeys-hook'
import { useValues } from 'kea'
import { useCommands, useCommandsSearch, CommandResult as CommandResultType } from './commandLogic'
import { globalCommands } from './globalCommands'
import { CommandSearch } from './CommandSearch'
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
    position: absolute;
    top: 30%;
    display: flex;
    flex-direction: column;
    z-index: 9999;
    width: 700px;
    min-height: 200px;
    max-height: 60%;
    box-shadow: 1px 4px 6px rgba(0, 0, 0, 0.1);
    border-radius: 10px;
    overflow: hidden;
`
/*const ResultsGroup = styled.div`
    background-color: #4d4d4d;
    height: 22px;
    width: 100%;
    box-shadow: 0px 2px 4px rgba(0, 0, 0, 0.1);
    padding-left: 16px;
    padding-right: 16px;
    text-transform: uppercase;
    color: rgba(255, 255, 255, 0.9);
    font-weight: bold;
`*/

const Title = styled.div`
    font-weight: bold;
    font-size: 14px;
    color: #ffffff;
    padding-top: 8px;
    padding-left: 16px;
`

const ResultsContainer = styled.div`
    overflow-y: scroll;
    padding-top: 8px;
`

const PaletteError = styled.div`
    color: #ec6f48;
    font-size: 14px;
    padding-top: 8px;
    padding-left: 32px;
    padding-right: 32px;
`

export function CommandPalette(): JSX.Element | null {
    const boxRef = useRef<HTMLDivElement | null>(null)
    const [state] = useState({ error: null, title: null })
    const [input, setInput] = useState('')
    const [isPaletteShown, setIsPaletteShown] = useState(false)
    const { push } = useActions(router)
    const { user } = useValues(userLogic)

    const handleCommandSelection = (result: CommandResultType): void => {
        // Called after a command is selected by the user
        result.executor({ push })
        setIsPaletteShown(false)
        setInput('')
    }
    const [activeResultIndex, setActiveResultIndex] = useState(0)

    useHotkeys('cmd+k', () => {
        setIsPaletteShown(!isPaletteShown)
    })

    useHotkeys('ctrl+k', () => {
        setIsPaletteShown(!isPaletteShown)
    })

    useHotkeys('esc', () => {
        setIsPaletteShown(false)
    })

    useOutsideClickHandler(boxRef, () => {
        setIsPaletteShown(false)
    })

    useCommands(globalCommands)

    useEffect(() => {
        // prevent scrolling when box is open
        document.body.style.overflow = isPaletteShown ? 'hidden' : ''
        setActiveResultIndex(0)
    }, [isPaletteShown])

    useEffect(() => {
        if (Object.keys(commandsSearch(input)).length - 1 > activeResultIndex) {
            setActiveResultIndex(0)
        }
    }, [input])

    const commandsSearch = useCommandsSearch()

    const _handleKeyDown = useCallback(
        (e: KeyboardEvent) => {
            if (isPaletteShown) {
                if (e.key === 'ArrowDown') {
                    setActiveResultIndex((prevIndex) => {
                        if (prevIndex === Object.keys(commandsSearch(input)).length - 1) return prevIndex
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
                handleCommandSelection(commandsSearch(input)[activeResultIndex])
            }
        },
        [activeResultIndex, input]
    )

    useEventListener('keydown', _handleEnterDown)

    return !user || !isPaletteShown ? null : (
        <CommandPaletteContainer>
            <CommandPaletteBox ref={boxRef} className="bg-dark">
                {state.title && <Title>{state.title}</Title>}
                <CommandSearch
                    onClose={() => {
                        setIsPaletteShown(false)
                    }}
                    input={input}
                    setInput={setInput}
                />
                {state.error && <PaletteError>{state.error}</PaletteError>}
                <ResultsContainer>
                    {commandsSearch(input).map((result, index) => (
                        <CommandResult
                            focused={activeResultIndex === index}
                            key={`command-result-${index}`}
                            result={result}
                            handleSelection={handleCommandSelection}
                            onMouseOver={(): void => setActiveResultIndex(index)}
                        />
                    ))}
                </ResultsContainer>
            </CommandPaletteBox>
        </CommandPaletteContainer>
    )
}
