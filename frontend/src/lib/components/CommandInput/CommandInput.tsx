import { DropdownMenuGroup } from '@radix-ui/react-dropdown-menu'
import React, { useEffect, useRef, useState } from 'react'

import { IconCheck } from '@posthog/icons'

import { IconBlank } from 'lib/lemon-ui/icons'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuOpenIndicator,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
} from 'lib/ui/DropdownMenu/DropdownMenu'
import { Label } from 'lib/ui/Label/Label'
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
            // Show all commands when slash is typed
            setFilteredCommands(commands)
            setShowDropdown(true)
            setFocusedIndex(0)
        } else if (showDropdown && newValue.includes('/')) {
            const searchTerm = newValue.split('/').pop()?.toLowerCase() || ''
            const filtered = commands.filter((cmd) => cmd.displayName.toLowerCase().includes(searchTerm))
            setFilteredCommands(filtered)
            setFocusedIndex(0)
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
        // Small delay to ensure dropdown closes before focusing
        setTimeout(() => {
            inputRef.current?.focus()
        }, 1)
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
        e.stopPropagation()

        switch (e.key) {
            case '/':
                if (!showDropdown) {
                    e.preventDefault()
                    setFilteredCommands(commands)
                    setShowDropdown(true)
                    setFocusedIndex(0)
                    // Don't add the '/' to the input value
                    return
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
                <DropdownMenu open={showDropdown} onOpenChange={setShowDropdown}>
                    <DropdownMenuTrigger asChild>
                        <ButtonPrimitive className="rounded-r-none text-primary" variant="panel">
                            Filters
                            <DropdownMenuOpenIndicator />
                        </ButtonPrimitive>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="start" className="min-w-[300px]">
                        <DropdownMenuGroup>
                            <Label intent="menu" className="pl-1">
                                Select all, or select multiple
                            </Label>
                            <DropdownMenuSeparator />
                            {filteredCommands.map((command, index) => {
                                const isActive = activeCommands.includes(command.value)
                                const isFocused = index === focusedIndex
                                return (
                                    <DropdownMenuItem asChild>
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
                                            <div className="flex items-center justify-center w-8">
                                                <IconCheck
                                                    className={cn(
                                                        'hidden size-4 group-hover:block group-hover:opacity-10',
                                                        {
                                                            'block opacity-10': isFocused && !isActive,
                                                            'block text-success': isActive,
                                                            'group-hover:opacity-100': isActive && !isFocused,
                                                        }
                                                    )}
                                                />
                                                <IconBlank
                                                    className={cn('hidden size-4 group-hover:hidden', {
                                                        block: !isFocused && !isActive,
                                                    })}
                                                />
                                            </div>

                                            <div className="font-medium text-primary">{command.displayName}</div>
                                        </ButtonPrimitive>
                                    </DropdownMenuItem>
                                )
                            })}
                        </DropdownMenuGroup>
                    </DropdownMenuContent>
                </DropdownMenu>

                <div className="h-full flex items-center py-1">
                    <hr className="h-full w-px bg-border-primary" />
                </div>

                {/* Input Field */}
                <TextInputPrimitive
                    ref={inputRef}
                    value={inputValue}
                    onChange={(e) => handleInputChange(e.target.value)}
                    onKeyDown={handleKeyDown}
                    placeholder={placeholder}
                    autoComplete="off"
                    className="pl-2 w-full border-none flex-1 h-full min-h-full"
                />
            </div>
        </div>
    )
}
