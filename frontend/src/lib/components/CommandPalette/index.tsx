import React, { useRef } from 'react'
import { useOutsideClickHandler } from 'lib/utils'
import { useHotkeys } from 'react-hotkeys-hook'
import { CommandResult as CommandResultType } from './commandLogic'
import { useMountedLogic, useValues, useActions } from 'kea'
import { commandLogic } from './commandLogic'
import { CommandInput } from './CommandInput'
import { CommandResults } from './CommandResults'
import { userLogic } from 'scenes/userLogic'
import { ApiKeyCommand } from './CustomCommands/ApiKeyCommand'
import './index.scss'

export function CommandPalette(): JSX.Element | null {
    useMountedLogic(commandLogic)

    const { hidePalette, togglePalette, setSearchInput } = useActions(commandLogic)
    const { isPaletteShown } = useValues(commandLogic)
    const { user } = useValues(userLogic)
    const { customCommand } = useValues(commandLogic)
    const { setCustomCommand } = useActions(commandLogic)

    const boxRef = useRef<HTMLDivElement | null>(null)

    useHotkeys('cmd+k,ctrl+k', () => {
        togglePalette()
    })
    useHotkeys('esc', () => {
        hidePalette()
    })
    useOutsideClickHandler(boxRef, hidePalette)

    const handleCommandSelection = (result: CommandResultType): void => {
        // Called after a command is selected by the user
        result.executor()
        // Capture command execution, without useless data
        // eslint-disable-next-line @typescript-eslint/no-unused-vars
        const { icon, index, ...cleanedResult } = result
        // eslint-disable-next-line @typescript-eslint/no-unused-vars
        const { resolver, ...cleanedCommand } = cleanedResult.command
        cleanedResult.command = cleanedCommand
        window.posthog?.capture('palette command executed', cleanedResult)
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
                <div className="palette__container">
                    {!customCommand && (
                        <div className="palette__box card bg-dark" ref={boxRef}>
                            <CommandInput />
                            <CommandResults handleCommandSelection={handleCommandSelection} />
                        </div>
                    )}
                    {customCommand && (
                        <>
                            {customCommand === 'create_api_key' && (
                                <ApiKeyCommand handleCancel={handleCancelCustomCommand} />
                            )}
                        </>
                    )}
                </div>
            )}
        </>
    )
}
