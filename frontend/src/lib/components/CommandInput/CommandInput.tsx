import React, { useEffect, useRef, useState } from 'react'

import { IconCheck } from '@posthog/icons'
import { LemonInput } from '@posthog/lemon-ui'
import { LemonTag } from '@posthog/lemon-ui'

import { IconBlank } from 'lib/lemon-ui/icons'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { cn } from 'lib/utils/css-classes'

export interface Command<T = string> {
    value: T
    displayName: string
}

interface CommandInputProps<T = string> {
    commands: Command<T>[]
    placeholder?: string
    value?: string
    onChange?: (value: string) => void
    onCommandSelect?: (command: Command<T>) => void
    selectedCommands?: Command<T>[]
    onSelectedCommandsChange?: (commands: Command<T>[]) => void
    activeCommands?: T[]
}

export function CommandInput<T = string>({
    commands,
    placeholder = 'Type / to see commands...',
    value = '',
    onChange,
    onCommandSelect,
    selectedCommands = [],
    onSelectedCommandsChange,
    activeCommands = [],
}: CommandInputProps<T>): JSX.Element {
    const [inputValue, setInputValue] = useState(value)
    const [showDropdown, setShowDropdown] = useState(false)
    const [filteredCommands, setFilteredCommands] = useState<Command<T>[]>([])
    const [focusedIndex, setFocusedIndex] = useState(0)
    const inputRef = useRef<HTMLInputElement>(null)
    const dropdownRef = useRef<HTMLDivElement>(null)

    useEffect(() => {
        setInputValue(value)
    }, [value])

    const handleInputChange = (newValue: string): void => {
        setInputValue(newValue)
        onChange?.(newValue)

        if (newValue.endsWith('/')) {
            setFilteredCommands(commands)
            setShowDropdown(true)
            setFocusedIndex(0)
        } else if (showDropdown && newValue.includes('/')) {
            const searchTerm = newValue.split('/').pop()?.toLowerCase() || ''
            const filtered = commands.filter((cmd) => cmd.displayName.toLowerCase().includes(searchTerm))
            setFilteredCommands(filtered)
            setFocusedIndex(0)
        } else {
            setShowDropdown(false)
        }
    }

    const selectCommand = (command: Command<T>): void => {
        const newSelectedCommands = selectedCommands.some((cmd) => cmd.value === command.value)
            ? selectedCommands
            : [...selectedCommands, command]

        onSelectedCommandsChange?.(newSelectedCommands)
        onCommandSelect?.(command)

        // Remove the /command part from input
        const lastSlashIndex = inputValue.lastIndexOf('/')
        const newInputValue = inputValue.substring(0, lastSlashIndex)
        setInputValue(newInputValue)
        onChange?.(newInputValue)
        setShowDropdown(false)
        inputRef.current?.focus()
    }

    const removeCommand = (commandValue: string): void => {
        const newSelectedCommands = selectedCommands.filter((cmd) => cmd.value !== commandValue)
        onSelectedCommandsChange?.(newSelectedCommands)
    }

    const handleBlur = (): void => {
        if (inputValue === '/' && showDropdown) {
            setShowDropdown(false)
            setInputValue('')
        }
        // Delay hiding dropdown to allow for clicks
        setTimeout(() => {
            if (!dropdownRef.current?.contains(document.activeElement)) {
                setShowDropdown(false)
            }
        }, 100)
    }

    const scrollFocusedCommandToView = (): void => {
        if (focusedIndex >= 0 && dropdownRef.current) {
            // Use a small timeout to ensure DOM has updated
            setTimeout(() => {
                const element = dropdownRef.current?.querySelector('.command-input-focused')
                if (element) {
                    element.scrollIntoView({ behavior: 'smooth', block: 'center', inline: 'center' })
                }
            }, 0)
        }
    }

    const handleKeyDown = (e: React.KeyboardEvent): void => {
        if (!showDropdown) {
            return
        }
        e.stopPropagation()

        switch (e.key) {
            case 'ArrowDown':
                e.preventDefault()
                setFocusedIndex((prev) => (prev + 1) % filteredCommands.length)
                break
            case 'ArrowUp':
                e.preventDefault()
                setFocusedIndex((prev) => (prev - 1 + filteredCommands.length) % filteredCommands.length)
                break
            case 'Enter':
                e.preventDefault()
                e.stopPropagation()
                if (filteredCommands[focusedIndex]) {
                    selectCommand(filteredCommands[focusedIndex])
                }
                break
            case 'Escape':
                e.preventDefault()
                setShowDropdown(false)
                if (inputValue === '/') {
                    setInputValue('')
                }
                break
        }
    }

    // scroll focused command to view
    useEffect(() => {
        if (focusedIndex >= 0) {
            scrollFocusedCommandToView()
        }
    }, [focusedIndex])

    return (
        <div className="relative w-full">
            {/* Selected Commands Tags */}
            {selectedCommands.length > 0 && (
                <div className="flex flex-wrap gap-1 mb-2">
                    {selectedCommands.map((command) => (
                        <LemonTag
                            key={command.value as string}
                            closable
                            onClose={() => removeCommand(command.value as string)}
                        >
                            {command.displayName}
                        </LemonTag>
                    ))}
                </div>
            )}

            {/* Input Field */}
            <LemonInput
                inputRef={inputRef}
                value={inputValue}
                onChange={handleInputChange}
                onKeyDown={handleKeyDown}
                onBlur={handleBlur}
                placeholder={placeholder}
                autoComplete="off"
                className="w-full"
            />

            {/* Commands Dropdown */}
            {showDropdown && filteredCommands.length > 0 && (
                <div
                    ref={dropdownRef}
                    className="flex flex-col gap-px p-1 absolute z-50 w-full mt-1 bg-surface-primary border border-primary shadow rounded-lg overflow-y-auto show-scrollbar-on-hover"
                >
                    {filteredCommands.map((command, index) => {
                        const isActive = activeCommands.includes(command.value)
                        const isFocused = index === focusedIndex
                        return (
                            <ButtonPrimitive
                                key={command.value as string}
                                className={`group ${
                                    isFocused ? 'command-input-focused' : ''
                                } flex items-center text-left`}
                                onClick={() => selectCommand(command)}
                                active={isFocused}
                                fullWidth
                                menuItem
                            >
                                <div className="flex items-center justify-center size-8">
                                    <IconCheck
                                        className={cn('hidden size-4 group-hover:block group-hover:opacity-10', {
                                            'block opacity-10': isFocused && !isActive,
                                            'block text-success': isActive,
                                            'group-hover:opacity-100': isActive && !isFocused,
                                        })}
                                    />
                                    <IconBlank
                                        className={cn('hidden size-4 group-hover:hidden', {
                                            block: !isFocused && !isActive,
                                        })}
                                    />
                                </div>

                                <div className="font-medium text-primary">{command.displayName}</div>
                            </ButtonPrimitive>
                        )
                    })}
                </div>
            )}
        </div>
    )
}
