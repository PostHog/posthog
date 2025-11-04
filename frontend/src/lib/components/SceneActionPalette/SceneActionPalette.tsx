import { useActions, useValues } from 'kea'
import React, { useCallback, useEffect, useRef } from 'react'
import { createPortal } from 'react-dom'

import { IconArrowRight } from '@posthog/icons'
import { LemonSwitch } from '@posthog/lemon-ui'

import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { DropdownMenuSeparator } from 'lib/ui/DropdownMenu/DropdownMenu'
import { Label } from 'lib/ui/Label/Label'
import { ListBoxHandle } from 'lib/ui/ListBox/ListBox'
import { sceneLogic } from 'scenes/sceneLogic'

import { KeyboardShortcut } from '~/layout/navigation-3000/components/KeyboardShortcut'
import { Combobox } from '~/lib/ui/Combobox/Combobox'

import type { SceneShortcut } from '../Scenes/SceneShortcut/SceneShortcut'

function getShortcutIcon(shortcut: SceneShortcut): JSX.Element | null {
    switch (shortcut.type) {
        case 'toggle':
            return (
                <div className="flex items-center gap-1 size-4">
                    <LemonSwitch checked={shortcut.active ?? false} size="xsmall" />
                </div>
            )
        case 'link':
            return (
                <div className="flex items-center gap-1 size-4">
                    <IconArrowRight className="w-4 h-4 text-muted" />
                </div>
            )
        case 'action':
        default:
            return (
                <div className="flex items-center gap-1 size-4">
                    <IconArrowRight className="w-4 h-4 text-muted" />
                </div>
            )
    }
}

export function SceneActionPalette(): JSX.Element | null {
    const { actionPaletteOpen, activeSceneShortcuts } = useValues(sceneLogic)
    const { setActionPaletteOpen } = useActions(sceneLogic)
    const comboboxRef = useRef<ListBoxHandle>(null)

    // Group shortcuts by sceneKey, with scene-specific first and app shortcuts last
    const groupedShortcuts = React.useMemo(() => {
        const groups: Record<string, SceneShortcut[]> = {}

        activeSceneShortcuts.forEach((shortcut) => {
            // Normalize the key - convert Scene enum values to strings and handle undefined
            let key = 'app'
            if (shortcut.sceneKey) {
                // Convert Scene enum to string if needed, or use as-is if already string
                const rawKey = typeof shortcut.sceneKey === 'string' ? shortcut.sceneKey : String(shortcut.sceneKey)
                // Normalize to lowercase to handle case inconsistencies
                key = rawKey.toLowerCase()
            }

            if (!groups[key]) {
                groups[key] = []
            }
            groups[key].push(shortcut)
        })

        // Sort groups: scene-specific first, then 'app' last
        const sortedGroupKeys = Object.keys(groups).sort((a, b) => {
            if (a === 'app') {
                return 1
            }
            if (b === 'app') {
                return -1
            }
            return a.localeCompare(b)
        })

        return sortedGroupKeys.map((key) => ({
            key,
            shortcuts: groups[key].sort((a, b) => {
                // Sort by order prop within each group
                const orderA = a.order ?? 0
                const orderB = b.order ?? 0
                return orderA - orderB
            }),
            title: key === 'app' ? 'General' : key.charAt(0).toUpperCase() + key.slice(1),
        }))
    }, [activeSceneShortcuts])

    const handleClose = useCallback(() => {
        setActionPaletteOpen(false)
    }, [setActionPaletteOpen])

    const handleItemClick = useCallback(
        (shortcut: SceneShortcut) => {
            shortcut.action()

            if (shortcut.closeActionPaletteOnAction) {
                // Close the palette if the action requests it (e.g., opens a modal)
                handleClose()
            } else {
                // Keep the action palette open after executing an action
                // Users can press Escape or click outside to close it

                // Ensure search input stays focused and first item is selected after action execution
                setTimeout(() => {
                    const searchInput = document.querySelector('#scene-action-palette input') as HTMLInputElement
                    if (searchInput) {
                        searchInput.focus()
                    }
                    comboboxRef.current?.recalculateFocusableElements()
                    comboboxRef.current?.focusFirstItem()
                }, 10) // Small delay to allow DOM updates
            }
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
                    // Get the shortcut ID from the data attribute
                    const shortcutId = focusedElement.getAttribute('data-shortcut-id')
                    if (shortcutId) {
                        const shortcut = activeSceneShortcuts.find((s) => s.id === shortcutId)
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
        [handleClose, activeSceneShortcuts, handleItemClick]
    )

    useEffect(() => {
        if (actionPaletteOpen) {
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
    }, [actionPaletteOpen, handleClose])

    // Ensure search input is focused and first item is selected when shortcuts change
    useEffect(() => {
        if (actionPaletteOpen && activeSceneShortcuts.length > 0) {
            setTimeout(() => {
                const searchInput = document.querySelector('#scene-action-palette input') as HTMLInputElement
                if (searchInput) {
                    searchInput.focus()
                }
                comboboxRef.current?.recalculateFocusableElements()
                comboboxRef.current?.focusFirstItem()
            }, 0)
        }
    }, [actionPaletteOpen, activeSceneShortcuts])

    if (!actionPaletteOpen) {
        return null
    }

    const paletteContent = (
        <div className="fixed inset-0 z-top flex items-end justify-center p-6 backdrop-blur-[var(--modal-backdrop-blur)]">
            <div
                className="bg-surface-secondary border-3 border-tertiary rounded-lg shadow-2xl w-96 max-h-96 overflow-hidden backdrop-blur-sm"
                id="scene-action-palette"
                onKeyDown={handleKeyDown}
            >
                <Combobox ref={comboboxRef}>
                    <Combobox.Content>
                        {groupedShortcuts.length === 0 ? (
                            <Combobox.Empty>No actions available</Combobox.Empty>
                        ) : (
                            groupedShortcuts.map((group, groupIndex) => (
                                <React.Fragment key={group.key}>
                                    {groupIndex > 0 && <div className="h-px bg-border mx-2 my-1" />}
                                    <Label intent="menu" className="px-1">
                                        {group.title}
                                    </Label>
                                    <DropdownMenuSeparator />
                                    {group.shortcuts.map((shortcut, index) => {
                                        const isFirstItem = groupIndex === 0 && index === 0
                                        return (
                                            <Combobox.Group key={shortcut.id} value={[shortcut.description]}>
                                                <Combobox.Item focusFirst={isFirstItem} asChild>
                                                    <ButtonPrimitive
                                                        menuItem
                                                        data-shortcut-id={shortcut.id}
                                                        onClick={(e) => {
                                                            e.preventDefault()
                                                            e.stopPropagation()
                                                            handleItemClick(shortcut)
                                                        }}
                                                    >
                                                        <div className="flex items-center gap-2">
                                                            {getShortcutIcon(shortcut)}
                                                            {shortcut.description}
                                                        </div>
                                                        <span className="ml-auto">
                                                            <KeyboardShortcut
                                                                {...Object.fromEntries(
                                                                    shortcut.keys.map((key) => [key, true])
                                                                )}
                                                                className="text-xs"
                                                            />
                                                        </span>
                                                    </ButtonPrimitive>
                                                </Combobox.Item>
                                            </Combobox.Group>
                                        )
                                    })}
                                </React.Fragment>
                            ))
                        )}
                    </Combobox.Content>
                    <Combobox.Search
                        placeholder="Search actions... escape to close"
                        autoFocus
                        className="border-0 focus:ring-0 focus:border-0"
                    />
                </Combobox>
            </div>
            <div className="absolute inset-0 -z-10" onClick={handleClose} aria-hidden="true" />
        </div>
    )

    return createPortal(paletteContent, document.body)
}
