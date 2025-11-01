import { useActions, useValues } from 'kea'
import React, { useCallback, useEffect, useRef } from 'react'
import { createPortal } from 'react-dom'

import { IconArrowRight } from '@posthog/icons'
import { LemonSwitch } from '@posthog/lemon-ui'

import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { ListBoxHandle } from 'lib/ui/ListBox/ListBox'
import { sceneLogic } from 'scenes/sceneLogic'

import { KeyboardShortcut } from '~/layout/navigation-3000/components/KeyboardShortcut'
import { Combobox } from '~/lib/ui/Combobox/Combobox'

import type { SceneShortcut } from '../Scenes/SceneShortcut/SceneShortcut'

function getShortcutIcon(shortcut: SceneShortcut): JSX.Element | null {
    switch (shortcut.type) {
        case 'toggle':
            return <LemonSwitch checked={shortcut.active ?? false} size="small" />
        case 'link':
            return <IconArrowRight className="w-4 h-4 text-muted" />
        case 'action':
        default:
            return <IconArrowRight className="w-4 h-4 text-muted" />
    }
}

export function SceneActionPalette(): JSX.Element | null {
    const { actionPaletteOpen, activeSceneShortcuts } = useValues(sceneLogic)
    const { setActionPaletteOpen } = useActions(sceneLogic)
    const comboboxRef = useRef<ListBoxHandle>(null)

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
                    // Get the index of the focused item to find the corresponding shortcut
                    const allItems = document.querySelectorAll('#scene-action-palette [data-listbox-item]')
                    const focusedIndex = Array.from(allItems).indexOf(focusedElement)

                    if (focusedIndex >= 0 && focusedIndex < activeSceneShortcuts.length) {
                        const shortcut = activeSceneShortcuts[focusedIndex]
                        handleItemClick(shortcut)
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
        <div className="fixed inset-0 z-top flex items-end justify-center p-6">
            <div
                className="bg-surface-secondary border-3 border-tertiary rounded-lg shadow-2xl w-96 max-h-96 overflow-hidden backdrop-blur-sm"
                id="scene-action-palette"
                onKeyDown={handleKeyDown}
            >
                <Combobox ref={comboboxRef}>
                    <Combobox.Content>
                        <Combobox.Empty>No actions available</Combobox.Empty>
                        {activeSceneShortcuts.length === 0 ? (
                            <></>
                        ) : (
                            activeSceneShortcuts.map((shortcut, index) => (
                                <Combobox.Group key={shortcut.id} value={[shortcut.description]}>
                                    <Combobox.Item focusFirst={index === 0} asChild>
                                        <ButtonPrimitive
                                            menuItem
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
                                                    {...Object.fromEntries(shortcut.keys.map((key) => [key, true]))}
                                                    className="text-xs"
                                                />
                                            </span>
                                        </ButtonPrimitive>
                                    </Combobox.Item>
                                </Combobox.Group>
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
