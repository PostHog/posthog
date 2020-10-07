import { useOutsideClickHandler } from 'lib/utils'
import React, { useEffect, useState } from 'react'
import { useRef } from 'react'
import { useHotkeys } from 'react-hotkeys-hook'
import { useCommands, useCommandsSearch } from './commandLogic'
import { globalCommands } from './globalCommands'
import { CommandSearch } from './CommandSearch'
import { CommandResult } from './CommandResult'
import styled from 'styled-components'

const PaletteContainer = styled.div`
    z-index: 9999;
    position: absolute;
    top: 50%;
    left: 50%;
    transform: translate(-50%, -50%);
    width: 700px;
    min-height: 200px;
    max-height: 60%;
    box-shadow: 1px 4px 6px rgba(0, 0, 0, 0.1);
    background-color: #373737;
    border-radius: 10px;
    display: flex;
    flex-direction: column;
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

interface BoxProps {
    visible: boolean
    onClickOutside: () => void
    onClose: () => void
}

export function CommandPalette({ visible, onClose }: BoxProps): JSX.Element | false {
    const boxRef = useRef<HTMLDivElement | null>(null)
    const [state] = useState({ error: null, title: null })
    const [input, setInput] = useState('')

    useHotkeys('esc', () => {
        onClose()
    })

    useOutsideClickHandler(boxRef, () => {
        onClose()
    })

    useCommands(globalCommands)

    useEffect(() => {
        // prevent scrolling when box is open
        document.body.style.overflow = visible ? 'hidden' : ''
    }, [visible])

    const commandsSearch = useCommandsSearch()

    return (
        visible && (
            <PaletteContainer ref={boxRef}>
                {state.title && <Title>{state.title}</Title>}
                <CommandSearch onClose={onClose} input={input} setInput={setInput} />
                {state.error && <PaletteError>{state.error}</PaletteError>}
                <ResultsContainer>
                    {/*<ResultsGroup>On this page</ResultsGroup>
                    <CommandResult
                        Icon={UserOutlined}
                        text="type an email address to go straight to that person’s page"
                        isHint
                    />
                    <CommandResult Icon={DashboardOutlined} text="go to dashboard AARRR" focused />
                    <CommandResult Icon={DashboardOutlined} text="go to dashboard AARRR" />
                    <CommandResult Icon={DashboardOutlined} text="go to dashboard AARRR" />
                    <CommandResult Icon={DashboardOutlined} text="go to dashboard AARRR" />
                    <ResultsGroup>Global</ResultsGroup>
                    <CommandResult Icon={DashboardOutlined} text="go to dashboard AARRR" />
                    <CommandResult Icon={DashboardOutlined} text="go to dashboard AARRR" />*/}
                    {commandsSearch(input).map((result, index) => (
                        <CommandResult
                            key={`command-result-${index}`}
                            Icon={result.icon}
                            text={result.text}
                            executor={result.executor}
                        />
                    ))}
                </ResultsContainer>
            </PaletteContainer>
        )
    )
}
