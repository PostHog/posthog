import { useActions, useValues } from 'kea'
import React, { useCallback, useEffect, useMemo, useRef } from 'react'
import { createPortal } from 'react-dom'

import { IconArrowRight } from '@posthog/icons'

import { IconAction } from 'lib/lemon-ui/icons'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { DropdownMenuSeparator } from 'lib/ui/DropdownMenu/DropdownMenu'
import { Label } from 'lib/ui/Label/Label'
import { ListBoxHandle } from 'lib/ui/ListBox/ListBox'
import { cn } from 'lib/utils/css-classes'
import { sceneLogic } from 'scenes/sceneLogic'
import { Scene } from 'scenes/sceneTypes'

import { KeyboardShortcut } from '~/layout/navigation-3000/components/KeyboardShortcut'
import { Combobox } from '~/lib/ui/Combobox/Combobox'

import { AppShortcutType, appShortcutLogic } from './appShortcutLogic'

function titleForKey(key: string): string {
    switch (key) {
        case 'global':
            return 'App'
        case Scene.SavedInsights:
            return 'Product Analytics'
        default:
            // Split capitalized case (e.g. ProductAnalytics -> Product Analytics)
            return key.replace(/([A-Z])/g, ' $1').replace(/^ /, '')
    }
}

function getShortcutIcon(shortcut: AppShortcutType): JSX.Element | null {
    switch (shortcut.interaction) {
        case 'focus':
            return (
                <div className="flex items-center gap-1 size-4">
                    <IconAction className="w-4 h-4 text-muted" />
                </div>
            )
        case 'click':
        default:
            return (
                <div className="flex items-center gap-1 size-4">
                    <IconArrowRight className="w-4 h-4 text-muted" />
                </div>
            )
    }
}

export function AppShortcutMenu(): JSX.Element | null {
    const { appShortcutMenuOpen } = useValues(appShortcutLogic)
    const { setAppShortcutMenuOpen } = useActions(appShortcutLogic)
    const { registeredAppShortcuts } = useValues(appShortcutLogic)
    const { activeTab } = useValues(sceneLogic)
    const comboboxRef = useRef<ListBoxHandle>(null)

    // Group shortcuts by scope, with scene-specific first and global last
    const groupedShortcuts = useMemo(() => {
        const groups: Record<string, AppShortcutType[]> = {}
        const currentScene = activeTab?.sceneId

        registeredAppShortcuts.forEach((shortcut) => {
            const scope = shortcut.scope || 'global'

            // Only include shortcuts that are global or match the current scene
            if (scope === 'global' || scope === currentScene) {
                if (!groups[scope]) {
                    groups[scope] = []
                }
                groups[scope].push(shortcut)
            }
        })

        // Sort groups: scene-specific first, then 'global' last
        const sortedGroupKeys = Object.keys(groups).sort((a, b) => {
            if (a === 'global') {
                return 1
            }
            if (b === 'global') {
                return -1
            }

            return a.localeCompare(b)
        })

        // Inside each group: priority first, then alphabetically
        for (const key of sortedGroupKeys) {
            groups[key].sort((a, b) => {
                const priorityDiff = (b.priority ?? 0) - (a.priority ?? 0)
                if (priorityDiff !== 0) {
                    return priorityDiff
                }

                return a.intent.localeCompare(b.intent)
            })
        }

        return sortedGroupKeys.map((key) => ({
            key,
            title: titleForKey(key),
            shortcuts: groups[key],
        }))
    }, [registeredAppShortcuts, activeTab])

    const handleClose = useCallback(() => {
        setAppShortcutMenuOpen(false)
    }, [setAppShortcutMenuOpen])

    const handleItemClick = useCallback(
        (shortcut: AppShortcutType) => {
            if (shortcut.interaction === 'click') {
                shortcut.ref.current?.click()
            } else if (shortcut.interaction === 'focus') {
                shortcut.ref.current?.focus()
            } else if (shortcut.interaction === 'function') {
                shortcut.callback()
            }

            // Always close the menu after executing a shortcut
            handleClose()
        },
        [handleClose]
    )

    const handleKeyDown = useCallback(
        (event: React.KeyboardEvent) => {
            if (event.key === 'Option') {
                event.preventDefault()
                event.stopPropagation()
                return
            }
            if (event.key === 'Escape') {
                event.preventDefault()
                handleClose()
            } else if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
                // Let the combobox handle arrow navigation
                return
            } else if (event.key === 'Enter') {
                // Handle Enter key directly to avoid ListBox focus issues
                event.preventDefault()
                event.stopPropagation()

                // Find the currently focused/selected shortcut by looking at the virtual focus
                const focusedElement = document.querySelector('#scene-action-palette [data-focused="true"]')
                if (focusedElement) {
                    // Get the shortcut name from the data attribute
                    const shortcutName = focusedElement.getAttribute('data-shortcut-name')
                    if (shortcutName) {
                        const shortcut = registeredAppShortcuts.find((s) => s.name === shortcutName)
                        if (shortcut) {
                            handleItemClick(shortcut)
                        }
                    }
                }
                return
            }

            // For any other key (typing in search), ensure search input stays focused and first item is selected
            if (event.target && (event.target as HTMLElement).tagName === 'INPUT') {
                setTimeout(() => {
                    const searchInput = document.querySelector('#scene-action-palette input') as HTMLInputElement
                    if (searchInput) {
                        searchInput.focus()
                    }
                    comboboxRef.current?.recalculateFocusableElements()
                    comboboxRef.current?.focusFirstItem()
                }, 50) // Slightly longer delay for search updates
            }
        },
        [handleClose, registeredAppShortcuts, handleItemClick]
    )

    useEffect(() => {
        if (appShortcutMenuOpen) {
            // Focus the search input when opened
            setTimeout(() => {
                const searchInput = document.querySelector('#scene-action-palette input') as HTMLInputElement
                if (searchInput) {
                    searchInput.focus()
                }
                // Also ensure first item is focused in listbox
                comboboxRef.current?.recalculateFocusableElements()
                comboboxRef.current?.focusFirstItem()
            }, 0)

            // Add escape key listener
            const handleEscape = (event: KeyboardEvent): void => {
                if (event.key === 'Escape') {
                    handleClose()
                }
            }

            window.addEventListener('keydown', handleEscape)
            return () => {
                window.removeEventListener('keydown', handleEscape)
            }
        }
    }, [appShortcutMenuOpen, handleClose])

    // Ensure search input is focused and first item is selected when shortcuts change
    useEffect(() => {
        if (appShortcutMenuOpen && registeredAppShortcuts.length > 0) {
            setTimeout(() => {
                const searchInput = document.querySelector('#scene-action-palette input') as HTMLInputElement
                if (searchInput) {
                    searchInput.focus()
                }
                comboboxRef.current?.recalculateFocusableElements()
                comboboxRef.current?.focusFirstItem()
            }, 0)
        }
    }, [appShortcutMenuOpen, registeredAppShortcuts])

    if (!appShortcutMenuOpen) {
        return null
    }

    const paletteContent = (
        <div className="fixed inset-0 z-[var(--z-shortcut-menu)] flex items-end justify-center p-6 backdrop-blur-[var(--modal-backdrop-blur)]">
            <div
                className="bg-surface-secondary border-3 border-tertiary rounded-lg shadow-2xl w-96 max-h-[calc(100vh-(var(--spacing)*6))] overflow-x-hidden overflow-y-auto backdrop-blur-sm"
                id="app-shortcut-menu"
                onKeyDown={handleKeyDown}
            >
                <Combobox ref={comboboxRef}>
                    <Combobox.Content>
                        <Combobox.Empty>No matching actions</Combobox.Empty>
                        {groupedShortcuts.map((group, groupIndex) => (
                            <React.Fragment key={group.key}>
                                <Combobox.Group value={group.shortcuts.map((s) => s.intent)}>
                                    <Label
                                        intent="menu"
                                        className={cn('px-1', {
                                            'pt-1': groupIndex > 0,
                                        })}
                                    >
                                        {group.title}
                                    </Label>
                                    <DropdownMenuSeparator />
                                </Combobox.Group>
                                {group.shortcuts.map((shortcut, index) => {
                                    const isFirstItem = groupIndex === 0 && index === 0
                                    return (
                                        <Combobox.Group key={shortcut.name} value={[shortcut.intent]}>
                                            <Combobox.Item focusFirst={isFirstItem} asChild>
                                                <ButtonPrimitive
                                                    menuItem
                                                    data-shortcut-name={shortcut.name}
                                                    onClick={(e) => {
                                                        e.preventDefault()
                                                        e.stopPropagation()
                                                        handleItemClick(shortcut)
                                                    }}
                                                    truncate
                                                >
                                                    <span className="flex items-center gap-2 truncate max-w-full">
                                                        {getShortcutIcon(shortcut)}
                                                        {shortcut.intent}
                                                    </span>
                                                    <span className="ml-auto flex items-center gap-1">
                                                        {(shortcut.keybind as string[][]).map(
                                                            (keybindOption, index) => (
                                                                <React.Fragment key={index}>
                                                                    {index > 0 && (
                                                                        <span className="text-xs opacity-75">or</span>
                                                                    )}
                                                                    <KeyboardShortcut
                                                                        {...Object.fromEntries(
                                                                            keybindOption.map((key: string) => [
                                                                                key,
                                                                                true,
                                                                            ])
                                                                        )}
                                                                        className="text-xs"
                                                                    />
                                                                </React.Fragment>
                                                            )
                                                        )}
                                                    </span>
                                                </ButtonPrimitive>
                                            </Combobox.Item>
                                        </Combobox.Group>
                                    )
                                })}
                            </React.Fragment>
                        ))}
                    </Combobox.Content>
                    <Combobox.Search
                        placeholder="Search actions... escape to close"
                        autoFocus
                        wrapperClassName="sticky bottom-0"
                    />
                </Combobox>
            </div>
            <div className="absolute inset-0 -z-10" onClick={handleClose} aria-hidden="true" />
        </div>
    )

    return createPortal(paletteContent, document.body)
}
