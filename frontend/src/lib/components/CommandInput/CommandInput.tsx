import React, { useEffect, useRef, useState } from 'react'

import { IconCheck, IconX } from '@posthog/icons'

import { IconBlank } from 'lib/lemon-ui/icons'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { TextInputPrimitive, textInputVariants } from 'lib/ui/TextInputPrimitive/TextInputPrimitive'
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
    const [focusedTagIndex, setFocusedTagIndex] = useState<number | null>(null)

    useEffect(() => {
        setInputValue(value)
    }, [value])

    const handleInputChange = (newValue: string): void => {
        setInputValue(newValue)
        onChange?.(newValue)

        // Clear focused tag when user starts typing
        if (focusedTagIndex !== null) {
            setFocusedTagIndex(null)
        }

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
        const commandToRemove = selectedCommands.find((cmd) => cmd.value === commandValue)
        const newSelectedCommands = selectedCommands.filter((cmd) => cmd.value !== commandValue)
        onSelectedCommandsChange?.(newSelectedCommands)

        // Notify parent component about the command removal
        if (commandToRemove) {
            onCommandSelect?.(commandToRemove)
        }
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
        // Handle escape key to clear focused tag or close dropdown
        if (e.key === 'Escape') {
            e.preventDefault()
            if (focusedTagIndex !== null) {
                // If a tag is focused, clear the focus
                setFocusedTagIndex(null)
                return
            } else if (showDropdown) {
                // If dropdown is open, close it
                setShowDropdown(false)
                if (inputValue === '/') {
                    setInputValue('')
                }
                return
            }
        }

        // Handle backspace for tag deletion regardless of dropdown state
        if (e.key === 'Backspace' && selectedCommands.length > 0 && inputValue === '') {
            e.preventDefault()
            if (focusedTagIndex !== null) {
                // If a tag is focused, delete it and clear focus
                removeCommand(selectedCommands[focusedTagIndex].value as string)
                setFocusedTagIndex(null)
            } else {
                // If no tag is focused, focus the last tag
                setFocusedTagIndex(selectedCommands.length - 1)
            }
            return
        }

        // Handle dropdown navigation only when dropdown is showing
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
            <div
                className={cn(
                    textInputVariants({
                        variant: 'default',
                        size: 'default',
                    }),
                    'flex gap-0 focus-within:border-secondary p-0 items-center h-8'
                )}
            >
                {selectedCommands.length > 0 && (
                    <div className="flex flex-wrap gap-1 h-full py-1 pl-1">
                        {selectedCommands.map((command, index) => (
                            <div
                                key={command.value as string}
                                className={cn('flex items-center gap-0.5 text-xxs h-full border rounded-sm pl-1 pr-0', {
                                    'border-danger bg-danger-highlight': focusedTagIndex === index,
                                    'border-primary': focusedTagIndex !== index,
                                })}
                                onClick={() => inputRef.current?.focus()}
                            >
                                {command.displayName}
                                <ButtonPrimitive
                                    size="xxs"
                                    className={cn('text-xxs h-full rounded-xs rounded-l-none', {
                                        'bg-danger text-primary-alt': focusedTagIndex === index,
                                        'hover:bg-bg-3000': focusedTagIndex !== index,
                                    })}
                                    onClick={() => {
                                        removeCommand(command.value as string)
                                    }}
                                >
                                    <IconX />
                                </ButtonPrimitive>
                            </div>
                        ))}
                    </div>
                )}

                {/* Input Field */}
                <TextInputPrimitive
                    ref={inputRef}
                    value={inputValue}
                    onChange={(e) => handleInputChange(e.target.value)}
                    onKeyDown={handleKeyDown}
                    onBlur={handleBlur}
                    placeholder={placeholder}
                    autoComplete="off"
                    className={cn('w-full border-none flex-1 h-full min-h-full', {
                        'pl-1': selectedCommands.length > 0,
                    })}
                />
            </div>

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
