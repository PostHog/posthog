import React, { useRef } from 'react'
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

    const { hidePalette, togglePalette, setSearchInput } = useActions(commandLogic)
    const { isPaletteShown } = useValues(commandLogic)
    const { user } = useValues(userLogic)
    const { customCommand } = useValues(commandLogic)
    const { setCustomCommand } = useActions(commandLogic)

    const boxRef = useRef<HTMLDivElement | null>(null)

    useHotkeys('cmd+k,ctrl+k', () => {
        console.log('c+k clicked')
        togglePalette()
    })
    useHotkeys('esc', () => {
        hidePalette()
    })
    useOutsideClickHandler(boxRef, hidePalette)

    const handleCommandSelection = (result: CommandResultType): void => {
        // Called after a command is selected by the user
        result.executor()
        if (!result.custom_command) {
            // The command palette container is kept on the DOM for custom commands,
            // the input is not cleared to ensure consistent navigation.
            hidePalette()
            setSearchInput('')
        }
    }

    const handleCancelCustomCommand = (): void => {
        // Trigerred after a custom command is cancelled
        setCustomCommand('')
    }

    return (
        <>
            {!user || !isPaletteShown ? null : (
                <CommandPaletteContainer>
                    {!customCommand && (
                        <CommandPaletteBox ref={boxRef} className="card bg-dark">
                            <CommandInput />
                            <CommandResults handleCommandSelection={handleCommandSelection} />
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
