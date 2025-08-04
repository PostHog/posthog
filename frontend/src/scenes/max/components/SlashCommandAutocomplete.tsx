import { offset } from '@floating-ui/react'
import { IconMemory, IconRocket } from '@posthog/icons'
import { LemonMenu, LemonMenuItem } from 'lib/lemon-ui/LemonMenu'
import { useEffect, useMemo, useState } from 'react'

export interface SlashCommand {
    name: `/${string}`
    arg?: `[${string}]`
    description: string
    icon: JSX.Element
}

export const MAX_SLASH_COMMANDS: SlashCommand[] = [
    {
        name: '/init',
        description: 'Set up knowledge about your product & business',
        icon: <IconRocket />,
    },
    {
        name: '/remember',
        arg: '[information]',
        description: "Add [information] to Max's project-level memory",
        icon: <IconMemory />,
    },
]

interface SlashCommandAutocompleteProps {
    /** Enter click - activate the command. */
    onActivate: (command: SlashCommand) => void
    /** Right arrow click - set input value without activating the command. */
    onSelect: (command: SlashCommand) => void
    onClose: () => void
    visible: boolean
    searchText: string
    children: React.ReactElement
}
// Convert Command to LemonMenuItem
const slashCommandToMenuItem = (
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

export function SlashCommandAutocomplete({
    onActivate,
    onSelect,
    onClose,
    visible,
    searchText,
    children,
}: SlashCommandAutocompleteProps): JSX.Element {
    const filteredCommands = useMemo(() => {
        return MAX_SLASH_COMMANDS.filter((command) => command.name.toLowerCase().startsWith(searchText.toLowerCase()))
    }, [searchText])

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
                onSelect(filteredCommands[activeItemIndex]) // And do NOT prevent default
            } else if (e.key === 'Escape') {
                e.preventDefault()
                onClose()
            } else if (e.key === 'Enter') {
                e.preventDefault()
                e.stopPropagation()
                onActivate(filteredCommands[activeItemIndex])
            }
        }
        document.addEventListener('keydown', handleKeyDown, { capture: true }) // Capture phase to run this before LemonTextArea's onEnter
        return () => document.removeEventListener('keydown', handleKeyDown, { capture: true })
    }, [visible, filteredCommands, activeItemIndex, onActivate, onSelect, onClose])

    return (
        <LemonMenu
            items={filteredCommands
                .map((command, index) => slashCommandToMenuItem(command, onActivate, index === activeItemIndex))
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
