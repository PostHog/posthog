import React, { useState, useRef, useEffect } from 'react'
import { useOutsideClickHandler } from 'lib/utils'
import { useHotkeys } from 'react-hotkeys-hook'
import { CommandResult as CommandResultType } from './commandLogic'
import { useMountedLogic, useValues, useActions } from 'kea'
import { commandLogic } from './commandLogic'
import { CommandInput } from './CommandInput'
import { CommandResults } from './CommandResults'
import styled from 'styled-components'
import { userLogic } from 'scenes/userLogic'
import { ApiKeyCommand } from './CustomCommands/ApiKeyCommand'

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
    width: 36rem;
    max-height: 60%;
    overflow: hidden;
`

export function CommandPalette(): JSX.Element | null {
    useMountedLogic(commandLogic)

    const { setSearchInput: setInput } = useActions(commandLogic)
    const { searchInput: input, commandSearchResults } = useValues(commandLogic)
    const { user } = useValues(userLogic)
    const { customCommand } = useValues(commandLogic)
    const { setCustomCommand } = useActions(commandLogic)

    const [isPaletteShown, setIsPaletteShown] = useState(false)

    const boxRef = useRef<HTMLDivElement | null>(null)

    const togglePalette = (): void => {
        setIsPaletteShown(!isPaletteShown)
        setCustomCommand('')
        setInput('')
    }

    useHotkeys('cmd+k,ctrl+k', togglePalette)

    useHotkeys('esc', togglePalette)

    useOutsideClickHandler(boxRef, togglePalette)

    const handleCommandSelection = (result: CommandResultType): void => {
        // Called after a command is selected by the user
        result.executor()
        if (!result.custom_command) {
            // The command palette container is kept on the DOM for custom commands,
            // the input is not cleared to ensure consistent navigation.
            setIsPaletteShown(false)
            setInput('')
        }
    }

    const handleCancelCustomCommand = (): void => {
        // Trigerred after a custom command is cancelled
        setCustomCommand('')
    }

    useEffect(() => {
        // prevent scrolling when box is open
        document.body.style.overflow = isPaletteShown ? 'hidden' : ''
    }, [isPaletteShown])

    return (
        <>
            {!user || !isPaletteShown ? null : (
                <CommandPaletteContainer>
                    {!customCommand && (
                        <CommandPaletteBox ref={boxRef} className="card bg-dark">
                            <CommandInput setIsPaletteShown={setIsPaletteShown} input={input} setInput={setInput} />
                            <CommandResults
                                results={commandSearchResults}
                                isPaletteShown={isPaletteShown}
                                handleCommandSelection={handleCommandSelection}
                            />
                        </CommandPaletteBox>
                    )}
                    {customCommand && (
                        <>
                            {customCommand === 'create_api_key' && (
                                <ApiKeyCommand handleCancel={handleCancelCustomCommand} />
                            )}
                        </>
                    )}
                </CommandPaletteContainer>
            )}
        </>
    )
}
