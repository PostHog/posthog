import { useOutsideClickHandler } from 'lib/utils'
import React, { useEffect, useState } from 'react'
import { useRef } from 'react'
import { useHotkeys } from 'react-hotkeys-hook'
import { isMac } from 'lib/utils'
import { useCommands, useCommandsSearch } from './commandLogic'
import { globalCommands } from './globalCommands'
import { CommandSearch } from './CommandSearch'
import { CommandResult } from './CommandResult'
import styled from 'styled-components'

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
    background-color: #373737;
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

export function CommandPalette(): JSX.Element | false {
    const boxRef = useRef<HTMLDivElement | null>(null)
    const [state] = useState({ error: null, title: null })
    const [input, setInput] = useState('')
    const [isPaletteShown, setIsPaletteShown] = useState(false)

    useHotkeys(isMac() ? 'cmd+k' : 'ctrl+k', () => {
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
    }, [isPaletteShown])

    const commandsSearch = useCommandsSearch()

    return (
        isPaletteShown && (
            <CommandPaletteContainer>
                <CommandPaletteBox ref={boxRef}>
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
                        {/*<ResultsGroup>On this page</ResultsGroup>
                    <CommandResult
                        Icon={UserOutlined}
                        text="type an email address to go straight to that person’s page"
                        isHint
                    />
                    <CommandResult Icon={DashboardOutlined} text="go to dashboard AARRR" focused />
                    <ResultsGroup>Global</ResultsGroup>
                    <CommandResult Icon={DashboardOutlined} text="go to Dashboard AARRR" />*/}
                        {commandsSearch(input).map((result, index) => (
                            <CommandResult
                                key={`command-result-${index}`}
                                result={result}
                                setIsPaletteShown={setIsPaletteShown}
                            />
                        ))}
                    </ResultsContainer>
                </CommandPaletteBox>
            </CommandPaletteContainer>
        )
    )
}
