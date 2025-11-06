import React, { forwardRef, useEffect, useImperativeHandle, useRef, useState } from 'react'

import { IconCheck, IconChevronRight, IconX } from '@posthog/icons'

import { IconBlank } from 'lib/lemon-ui/icons'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuGroup,
    DropdownMenuItem,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
} from 'lib/ui/DropdownMenu/DropdownMenu'
import { Label } from 'lib/ui/Label/Label'
import { ListBox } from 'lib/ui/ListBox/ListBox'
import { TextInputPrimitive, textInputVariants } from 'lib/ui/TextInputPrimitive/TextInputPrimitive'
import { cn } from 'lib/utils/css-classes'

import { KeyboardShortcut } from '~/layout/navigation-3000/components/KeyboardShortcut'

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
    onClearAll?: () => void
    enableCommands?: boolean
    onEmptyBackspace?: () => void
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
        onClearAll,
        enableCommands = true,
        onEmptyBackspace,
    }: SearchInputProps<T>,
    ref: React.Ref<SearchInputHandle>
) {
    const [inputValue, setInputValue] = useState(value)
    const [showDropdown, setShowDropdown] = useState(false)
    const [filteredCommands, setFilteredCommands] = useState<SearchInputCommand<T>[]>(commands)
    const inputRef = useRef<HTMLInputElement>(null)
    const [focusedTagIndex, setFocusedTagIndex] = useState<number | null>(null)
    const [expandedTags, setExpandedTags] = useState(false)

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

        if (!enableCommands) {
            if (showDropdown) {
                setShowDropdown(false)
            }
            return
        }

        // Clear focused tag and expanded state when user starts typing
        if (focusedTagIndex !== null) {
            setFocusedTagIndex(null)
        }
        if (expandedTags) {
            setExpandedTags(false)
        }

        if (newValue === '/') {
            // Show all commands when slash is typed as first character
            setFilteredCommands(commands)
            setShowDropdown(true)
        } else if (showDropdown && newValue.startsWith('/') && newValue.length > 1) {
            // Filter commands when typing after the initial slash
            const searchTerm = newValue.substring(1).toLowerCase()
            const filtered = commands.filter((cmd) => cmd.displayName.toLowerCase().includes(searchTerm))
            setFilteredCommands(filtered)
        } else if (showDropdown && !newValue.startsWith('/')) {
            // Hide dropdown if user removes the initial slash
            setShowDropdown(false)
        }
    }

    const selectCommand = (command: SearchInputCommand<T>): void => {
        const isSelected = selectedCommands.some((cmd) => cmd.value === command.value)
        const newSelectedCommands = isSelected
            ? selectedCommands.filter((cmd) => cmd.value !== command.value)
            : [...selectedCommands, command]

        onSelectedCommandsChange?.(newSelectedCommands)
        onCommandSelect?.(command)

        // Only clear input if it was in command mode (started with /)
        if (inputValue.startsWith('/')) {
            setInputValue('')
            onChange?.('')
        }

        // Reset tag focus state when selecting from dropdown
        setExpandedTags(false)
        setFocusedTagIndex(null)
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
                if (!enableCommands) {
                    break
                }
                if (!showDropdown && inputValue === '') {
                    // Only prevent default and show dropdown if input is empty
                    e.preventDefault()
                    setFilteredCommands(commands)
                    setShowDropdown(true)
                    return
                }
                // If input already has content, let the '/' be typed normally
                break
            case 'Backspace':
                if (inputValue === '') {
                    if (!enableCommands) {
                        if (onEmptyBackspace) {
                            e.preventDefault()
                            e.stopPropagation()
                            onEmptyBackspace()
                        }
                        break
                    }
                    e.preventDefault()
                    e.stopPropagation() // Prevent parent ListBox from handling this event
                    if (selectedCommands.length === 0) {
                        // No filters selected (showing "all"): open dropdown
                        setShowDropdown(true)
                    } else if (!expandedTags) {
                        // First backspace: expand tags and focus the last one
                        setExpandedTags(true)
                        setFocusedTagIndex(selectedCommands.length - 1)
                    } else if (focusedTagIndex !== null) {
                        // Second backspace: remove the focused tag
                        const commandToRemove = selectedCommands[focusedTagIndex]
                        selectCommand(commandToRemove)
                        setExpandedTags(false)
                        setFocusedTagIndex(null)
                    }
                }
                break
            case 'ArrowLeft':
                if (!enableCommands) {
                    break
                }
                if (e.metaKey) {
                    return
                }
                // Check if cursor is at the leftmost position
                const cursorPosition = inputRef.current?.selectionStart || 0
                const isAtLeftmostPosition = cursorPosition === 0

                if (inputValue === '') {
                    e.preventDefault()
                    e.stopPropagation() // Prevent parent ListBox from handling this event
                    if (selectedCommands.length === 0) {
                        // No filters selected (showing "all"): open dropdown
                        setShowDropdown(true)
                    } else if (!expandedTags && selectedCommands.length > 0) {
                        // Empty search + arrow left: expand tags and focus the last one
                        setExpandedTags(true)
                        setFocusedTagIndex(selectedCommands.length - 1)
                    } else if (expandedTags && focusedTagIndex !== null) {
                        if (focusedTagIndex > 0) {
                            setFocusedTagIndex(focusedTagIndex - 1)
                        } else {
                            // On first tag, focus the dropdown button
                            setFocusedTagIndex(-1) // -1 represents dropdown focus
                        }
                    }
                } else if (inputValue !== '' && isAtLeftmostPosition) {
                    // Cursor is at leftmost position with text: focus dropdown
                    e.preventDefault()
                    e.stopPropagation()
                    setExpandedTags(true)
                    setFocusedTagIndex(-1) // Focus dropdown button
                    setShowDropdown(true)
                }
                break
            case 'ArrowRight':
                if (!enableCommands) {
                    break
                }
                if (e.metaKey) {
                    return
                }
                if (inputValue === '' && expandedTags && focusedTagIndex !== null) {
                    e.preventDefault()
                    e.stopPropagation() // Prevent parent ListBox from handling this event
                    if (focusedTagIndex === -1) {
                        // From dropdown, move to first tag
                        setFocusedTagIndex(0)
                    } else if (focusedTagIndex < selectedCommands.length - 1) {
                        setFocusedTagIndex(focusedTagIndex + 1)
                    } else {
                        // On last tag, remove tag focus
                        setFocusedTagIndex(null)
                        setExpandedTags(false)
                    }
                }
                break
            case 'Enter':
                if (inputValue === '' && expandedTags && focusedTagIndex !== null) {
                    e.preventDefault()
                    e.stopPropagation() // Prevent parent ListBox from handling this event
                    if (focusedTagIndex === -1) {
                        // Enter on dropdown button: open dropdown
                        setShowDropdown(true)
                    } else {
                        // Enter on tag: remove the tag
                        const commandToRemove = selectedCommands[focusedTagIndex]
                        selectCommand(commandToRemove)
                        setExpandedTags(false)
                        setFocusedTagIndex(null)
                    }
                }
                break
            case 'ArrowDown':
                if (!enableCommands) {
                    break
                }
                if (inputValue === '' && expandedTags && focusedTagIndex === -1) {
                    e.preventDefault()
                    e.stopPropagation() // Prevent parent ListBox from handling this event
                    // Arrow down on dropdown button: open dropdown
                    setShowDropdown(true)
                }
                break
            case 'Escape':
                if (!enableCommands) {
                    break
                }
                if (showDropdown || expandedTags) {
                    e.preventDefault()
                    e.stopPropagation()
                    // Reset tag focus state when escaping
                    setExpandedTags(false)
                    setFocusedTagIndex(null)
                    setShowDropdown(false)
                }
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
                    'flex gap-1 focus-within:border-secondary items-center h-8 rounded-lg'
                )}
            >
                {enableCommands ? (
                    <DropdownMenu
                        open={showDropdown}
                        onOpenChange={(open) => {
                            setShowDropdown(open)
                        }}
                    >
                        <DropdownMenuTrigger asChild>
                            <ButtonPrimitive
                                variant="outline"
                                className={`ml-[calc(var(--button-padding-x-sm)+1px)] font-mono text-tertiary ${
                                    focusedTagIndex === -1 ? 'ring-2 ring-accent' : ''
                                }`}
                                iconOnly
                                size="sm"
                                tooltip={
                                    <>
                                        Click to show commands/filters, or type <KeyboardShortcut forwardslash />
                                    </>
                                }
                                tooltipPlacement="bottom"
                            >
                                /
                            </ButtonPrimitive>
                        </DropdownMenuTrigger>

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
                                <Label intent="menu" className="px-2">
                                    Filters
                                </Label>
                                <DropdownMenuSeparator />
                                {filteredCommands.map((command) => {
                                    const isActive = activeCommands.includes(command.value)
                                    return (
                                        <DropdownMenuItem key={command.value as string} asChild>
                                            <ButtonPrimitive
                                                className="group flex items-center text-left"
                                                onClick={() => selectCommand(command)}
                                                fullWidth
                                                menuItem
                                            >
                                                <div className="flex items-center justify-center">
                                                    <IconCheck
                                                        className={cn(
                                                            'hidden size-4 group-hover:block group-hover:opacity-10',
                                                            {
                                                                'opacity-10': !isActive,
                                                                'block text-success group-hover:opacity-100': isActive,
                                                            }
                                                        )}
                                                    />
                                                    <IconBlank
                                                        className={cn('hidden size-4 group-hover:hidden', {
                                                            block: !isActive,
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
                ) : null}

                {/* Selected inline tags */}
                {enableCommands &&
                    (selectedCommands.length === 0 ? null : selectedCommands.length === 1 || expandedTags ? (
                        selectedCommands.map((command, index) => (
                            <ButtonPrimitive
                                key={command.value as string}
                                className={`text-primary ${focusedTagIndex === index ? 'ring-2 ring-accent' : ''}`}
                                size="sm"
                                variant="outline"
                                onClick={() => {
                                    selectCommand(command)
                                    setShowDropdown(false)
                                    setExpandedTags(false)
                                    setFocusedTagIndex(null)
                                }}
                            >
                                {command.displayName}
                                <IconX className="size-3 ml-1 text-tertiary" />
                            </ButtonPrimitive>
                        ))
                    ) : (
                        <ButtonPrimitive
                            className="text-primary"
                            size="sm"
                            variant="outline"
                            onClick={() => setShowDropdown(true)}
                        >
                            {selectedCommands.length} filters
                            <IconChevronRight className="ml-1 rotate-90 text-tertiary" />
                        </ButtonPrimitive>
                    ))}
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
                    className="pl-1 w-full border-none flex-1 h-full min-h-full rounded-r-lg"
                    size="lg"
                    suffix={
                        (inputValue !== '' || (enableCommands && selectedCommands.length > 0)) && (
                            <ListBox.Item asChild>
                                <ButtonPrimitive
                                    iconOnly
                                    onClick={() => {
                                        setInputValue('')
                                        onChange?.('')
                                        // Reset all tag states
                                        if (enableCommands) {
                                            setExpandedTags(false)
                                            setFocusedTagIndex(null)
                                            setShowDropdown(false)
                                        }
                                        // Clear all filters if handler is provided
                                        if (enableCommands) {
                                            onClearAll?.()
                                        }
                                        inputRef.current?.focus()
                                    }}
                                    aria-label="Clear input and filters"
                                    size="sm"
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
