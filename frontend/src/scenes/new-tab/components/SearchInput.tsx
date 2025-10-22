import React, { forwardRef, useEffect, useImperativeHandle, useRef, useState } from 'react'

import { IconCheck, IconX } from '@posthog/icons'

import { IconBlank } from 'lib/lemon-ui/icons'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuGroup,
    DropdownMenuItem,
    DropdownMenuOpenIndicator,
    DropdownMenuTrigger,
} from 'lib/ui/DropdownMenu/DropdownMenu'
import { ListBox } from 'lib/ui/ListBox/ListBox'
import { TextInputPrimitive, textInputVariants } from 'lib/ui/TextInputPrimitive/TextInputPrimitive'
import { cn } from 'lib/utils/css-classes'

export interface SearchInputCommand<T = string> {
    value: T
    displayName: string
}

interface SearchInputProps<T = string> {
    commands: SearchInputCommand<T>[]
    placeholder?: string
    value?: string
    onChange?: (value: string) => void
    onCommandSelect?: (command: SearchInputCommand<T>) => void
    selectedCommands?: SearchInputCommand<T>[]
    onSelectedCommandsChange?: (commands: SearchInputCommand<T>[]) => void
    activeCommands?: T[]
}

export interface SearchInputHandle {
    focus: () => void
    getInputRef: () => React.RefObject<HTMLInputElement>
}

export const SearchInput = forwardRef<SearchInputHandle, SearchInputProps>(function SearchInput<T = string>(
    {
        commands,
        placeholder = 'Type / to see commands...',
        value = '',
        onChange,
        onCommandSelect,
        selectedCommands = [],
        onSelectedCommandsChange,
        activeCommands = [],
    }: SearchInputProps<T>,
    ref: React.Ref<SearchInputHandle>
) {
    const [inputValue, setInputValue] = useState(value)
    const [showDropdown, setShowDropdown] = useState(false)
    const [filteredCommands, setFilteredCommands] = useState<SearchInputCommand<T>[]>(commands)
    const [focusedIndex, setFocusedIndex] = useState(0)
    const inputRef = useRef<HTMLInputElement>(null)
    const [focusedTagIndex, setFocusedTagIndex] = useState<number | null>(null)

    useImperativeHandle(
        ref,
        () => ({
            focus: () => {
                if (inputRef.current) {
                    inputRef.current.focus()
                } else {
                }
            },
            getInputRef: () => inputRef,
        }),
        []
    )

    useEffect(() => {
        setInputValue(value)
    }, [value])

    useEffect(() => {
        setFilteredCommands(commands)
    }, [commands])

    const handleInputChange = (newValue: string): void => {
        setInputValue(newValue)
        onChange?.(newValue)

        // Clear focused tag when user starts typing
        if (focusedTagIndex !== null) {
            setFocusedTagIndex(null)
        }

        if (newValue === '/') {
            // Show all commands when slash is typed as first character
            setFilteredCommands(commands)
            setShowDropdown(true)
            setFocusedIndex(0)
        } else if (showDropdown && newValue.startsWith('/') && newValue.length > 1) {
            // Filter commands when typing after the initial slash
            const searchTerm = newValue.substring(1).toLowerCase()
            const filtered = commands.filter((cmd) => cmd.displayName.toLowerCase().includes(searchTerm))
            setFilteredCommands(filtered)
            setFocusedIndex(0)
        } else if (showDropdown && !newValue.startsWith('/')) {
            // Hide dropdown if user removes the initial slash
            setShowDropdown(false)
        }
    }

    const selectCommand = (command: SearchInputCommand<T>): void => {
        const newSelectedCommands = selectedCommands.some((cmd) => cmd.value === command.value)
            ? selectedCommands
            : [...selectedCommands, command]

        onSelectedCommandsChange?.(newSelectedCommands)
        onCommandSelect?.(command)

        // Only clear input if it was in command mode (started with /)
        if (inputValue.startsWith('/')) {
            setInputValue('')
            onChange?.('')
        }
        setShowDropdown(false)
        // Small delay to ensure dropdown closes before focusing
        setTimeout(() => {
            if (inputRef.current) {
                inputRef.current.focus()
            }
        }, 150)
    }

    const handleKeyDown = (e: React.KeyboardEvent): void => {
        switch (e.key) {
            case '/':
                if (!showDropdown && inputValue === '') {
                    // Only prevent default and show dropdown if input is empty (first character)
                    e.preventDefault()
                    setFilteredCommands(commands)
                    setShowDropdown(true)
                    setFocusedIndex(0)
                    setInputValue('/')
                    onChange?.('/')
                    return
                }
                // If input already has content, let the '/' be typed normally
                break
        }
    }

    return (
        <div className="relative w-full">
            <div
                className={cn(
                    textInputVariants({
                        variant: 'default',
                        size: 'lg',
                    }),
                    'flex gap-0 focus-within:border-secondary p-0 items-center h-8'
                )}
            >
                <DropdownMenu
                    open={showDropdown}
                    onOpenChange={(open) => {
                        setShowDropdown(open)
                    }}
                >
                    <ListBox.Item
                        asChild
                        onClick={(e) => {
                            e.stopPropagation()
                            setShowDropdown(true)
                        }}
                    >
                        <DropdownMenuTrigger asChild>
                            <ButtonPrimitive className="h-full rounded-r-none text-primary data-[focused=true]:outline-2 data-[focused=true]:outline-accent">
                                Filters
                                <DropdownMenuOpenIndicator />
                            </ButtonPrimitive>
                        </DropdownMenuTrigger>
                    </ListBox.Item>
                    <DropdownMenuContent
                        align="start"
                        className="min-w-[200px]"
                        onCloseAutoFocus={(e) => {
                            e.preventDefault()

                            setTimeout(() => {
                                if (inputRef.current) {
                                    inputRef.current.focus()
                                }
                            }, 100)
                        }}
                    >
                        <DropdownMenuGroup>
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

                <label className="h-full flex items-center py-1" htmlFor="command-input">
                    <hr className="h-full w-px bg-border-primary relative right-px" />
                </label>

                {/* Input Field */}
                <TextInputPrimitive
                    id="command-input"
                    ref={inputRef}
                    value={inputValue}
                    onChange={(e) => handleInputChange(e.target.value)}
                    onKeyDown={handleKeyDown}
                    placeholder={placeholder}
                    autoFocus
                    autoComplete="off"
                    className="pl-2 w-full border-none flex-1 h-full min-h-full"
                    size="lg"
                    suffix={
                        inputValue !== '' && (
                            <ListBox.Item asChild>
                                <ButtonPrimitive
                                    iconOnly
                                    onClick={() => {
                                        setInputValue('')
                                        inputRef.current?.focus()
                                    }}
                                    className="data-[focused=true]:outline-2 data-[focused=true]:outline-accent rounded-xs"
                                    aria-label="Clear input"
                                >
                                    <IconX />
                                </ButtonPrimitive>
                            </ListBox.Item>
                        )
                    }
                />
            </div>
        </div>
    )
})
