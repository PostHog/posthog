import { offset } from '@floating-ui/react'
import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { LemonMenu, LemonMenuItem } from 'lib/lemon-ui/LemonMenu'

import { maxThreadLogic } from '../maxThreadLogic'
import { MAX_SLASH_COMMANDS, SlashCommand } from '../slash-commands'

interface SlashCommandAutocompleteProps {
    onClose: () => void
    visible: boolean
    children: React.ReactElement
}

const convertSlashCommandToMenuItem = (
    command: SlashCommand,
    onActivate: (command: SlashCommand) => void,
    active: boolean
): LemonMenuItem => ({
    key: command.name,
    label: (
        <div>
            <div className="font-mono mt-0.5">
                {command.name}
                {command.arg && ` ${command.arg}`}
            </div>
            <div className="text-muted text-xs">{command.description}</div>
        </div>
    ),
    icon: command.icon,
    onClick: () => onActivate(command),
    active,
})

export function SlashCommandAutocomplete({ onClose, visible, children }: SlashCommandAutocompleteProps): JSX.Element {
    const { filteredCommands } = useValues(maxThreadLogic)
    const { selectCommand, activateCommand } = useActions(maxThreadLogic)

    const [activeItemIndex, setActiveItemIndex] = useState(filteredCommands.length - 1) // Highlight bottom-most command by default

    // Reset highlighted key when visibility changes or commands change
    useEffect(() => {
        setActiveItemIndex(filteredCommands.length - 1)
    }, [visible, filteredCommands])

    // Handle keyboard navigation
    useEffect(() => {
        if (!visible || filteredCommands.length === 0) {
            return
        }
        const handleKeyDown = (e: KeyboardEvent): void => {
            if (e.key === 'ArrowDown') {
                e.preventDefault()
                setActiveItemIndex(activeItemIndex < filteredCommands.length - 1 ? activeItemIndex + 1 : 0)
            } else if (e.key === 'ArrowUp') {
                e.preventDefault()
                setActiveItemIndex(activeItemIndex > 0 ? activeItemIndex - 1 : filteredCommands.length - 1)
            } else if (e.key === 'ArrowRight') {
                selectCommand(filteredCommands[activeItemIndex]) // And do NOT prevent default
            } else if (e.key === 'Escape') {
                e.preventDefault()
                onClose()
            } else if (e.key === 'Enter') {
                e.preventDefault()
                e.stopPropagation()
                activateCommand(filteredCommands[activeItemIndex])
            }
        }
        document.addEventListener('keydown', handleKeyDown, { capture: true }) // Capture phase to run this before LemonTextArea's onEnter
        return () => document.removeEventListener('keydown', handleKeyDown, { capture: true })
    }, [visible, filteredCommands, activeItemIndex, activateCommand, selectCommand, onClose])

    return (
        <LemonMenu
            items={filteredCommands
                .map((command: SlashCommand, index: number) =>
                    convertSlashCommandToMenuItem(command, activateCommand, index === activeItemIndex)
                )
                .concat([
                    {
                        key: 'navigation-hint',
                        label: function NavigationHintLabel() {
                            return <NavigationHint isArgRequired={!!filteredCommands[activeItemIndex]?.arg} />
                        },
                    },
                ])}
            visible={visible && filteredCommands.length > 0}
            onVisibilityChange={(visible) => {
                if (!visible) {
                    onClose()
                }
            }}
            closeOnClickInside
            onClickOutside={() => onClose()}
            placement="top-start"
            fallbackPlacements={['bottom-start']}
            middleware={[
                // Offset against the textarea's padding, to align the popover with the "/" character
                offset({
                    mainAxis: -8,
                    crossAxis: 8,
                }),
            ]}
            focusBasedKeyboardNavigation={false}
        >
            {children}
        </LemonMenu>
    )
}

function NavigationHint({ isArgRequired }: { isArgRequired: boolean }): JSX.Element {
    return (
        <div className="border-t px-1 pt-1.5 pb-0.5 mt-1 text-xxs text-muted-alt font-medium select-none">
            {MAX_SLASH_COMMANDS.length > 1 && '↑↓ to navigate • '}
            {!isArgRequired ? '⏎ to activate • → to select • Esc to close' : '⏎ or → to select • Esc to close'}
        </div>
    )
}
