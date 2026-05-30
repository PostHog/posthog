import { offset } from '@floating-ui/react'
import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { LemonMenu, LemonMenuItem } from 'lib/lemon-ui/LemonMenu'

import { maxThreadLogic } from '../maxThreadLogic'
import { MAX_SLASH_COMMANDS, SANDBOX_UNSUPPORTED_TOOLTIP, SlashCommand } from '../slash-commands'

interface SlashCommandAutocompleteProps {
    onClose: () => void
    visible: boolean
    children: React.ReactElement
}

const convertSlashCommandToMenuItem = (
    command: SlashCommand,
    onActivate: (command: SlashCommand) => void,
    active: boolean,
    disabled: boolean
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
    // Sandbox runtime: /init and /remember render disabled with the "Not yet supported" tooltip
    // (02_CORE § 8). LangGraph never sets this.
    disabledReason: disabled ? SANDBOX_UNSUPPORTED_TOOLTIP : undefined,
})

export function SlashCommandAutocomplete({ onClose, visible, children }: SlashCommandAutocompleteProps): JSX.Element {
    const { filteredCommands, isSandboxRuntime } = useValues(maxThreadLogic)
    const { selectCommand, activateCommand } = useActions(maxThreadLogic)

    const isDisabled = (command: SlashCommand): boolean => isSandboxRuntime && !!command.unsupportedInSandbox
    // Default highlight to the bottom-most enabled command; disabled (sandbox-unsupported) commands
    // are skipped by keyboard nav and never activate.
    const lastEnabledIndex = (): number => {
        for (let i = filteredCommands.length - 1; i >= 0; i--) {
            if (!isDisabled(filteredCommands[i])) {
                return i
            }
        }
        return filteredCommands.length - 1
    }

    const [activeItemIndex, setActiveItemIndex] = useState(lastEnabledIndex())

    // Reset highlighted key when visibility changes or commands change
    useEffect(() => {
        setActiveItemIndex(lastEnabledIndex())
    }, [visible, filteredCommands]) // oxlint-disable-line react-hooks/exhaustive-deps

    // Handle keyboard navigation
    useEffect(() => {
        if (!visible || filteredCommands.length === 0) {
            return
        }
        // Skip disabled (sandbox-unsupported) commands when stepping through the list.
        const step = (start: number, direction: 1 | -1): number => {
            const count = filteredCommands.length
            for (let i = 1; i <= count; i++) {
                const next = (start + direction * i + count * count) % count
                if (!isDisabled(filteredCommands[next])) {
                    return next
                }
            }
            return start
        }
        const handleKeyDown = (e: KeyboardEvent): void => {
            if (e.key === 'ArrowDown') {
                e.preventDefault()
                setActiveItemIndex(step(activeItemIndex, 1))
            } else if (e.key === 'ArrowUp') {
                e.preventDefault()
                setActiveItemIndex(step(activeItemIndex, -1))
            } else if (e.key === 'ArrowRight') {
                selectCommand(filteredCommands[activeItemIndex]) // And do NOT prevent default; no-op if disabled
            } else if (e.key === 'Escape') {
                e.preventDefault()
                onClose()
            } else if (e.key === 'Enter') {
                e.preventDefault()
                e.stopPropagation()
                activateCommand(filteredCommands[activeItemIndex]) // No-op if disabled
            }
        }
        document.addEventListener('keydown', handleKeyDown, { capture: true }) // Capture phase to run this before LemonTextArea's onEnter
        return () => document.removeEventListener('keydown', handleKeyDown, { capture: true })
    }, [visible, filteredCommands, activeItemIndex, activateCommand, selectCommand, onClose]) // oxlint-disable-line react-hooks/exhaustive-deps

    return (
        <LemonMenu
            matchWidth
            items={filteredCommands
                .map((command: SlashCommand, index: number) =>
                    convertSlashCommandToMenuItem(
                        command,
                        activateCommand,
                        index === activeItemIndex,
                        isDisabled(command)
                    )
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
