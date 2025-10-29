import { useActions, useValues } from 'kea'
import React, { useCallback, useEffect, useMemo, useRef } from 'react'

import { sceneLogic } from 'scenes/sceneLogic'
import { Scene } from 'scenes/sceneTypes'

import { KeyboardShortcut } from '~/layout/navigation-3000/components/KeyboardShortcut'
import { HotKeyOrModifier } from '~/types'

export interface SceneShortcut {
    id: string
    keys: HotKeyOrModifier[]
    description: string
    enabled: boolean
    action: () => void
    sceneKey?: Scene
    element?: HTMLElement
}

interface SceneShortcutProps {
    /** Array of keys that make up the shortcut (e.g., ['command', 'e']) */
    keys: HotKeyOrModifier[]
    /** Description of what this shortcut does */
    description: string
    /** Scene this shortcut belongs to */
    sceneKey: Scene
    /** Whether the shortcut is currently enabled */
    enabled?: boolean
    /** The action to perform when the shortcut is triggered */
    onAction: () => void
    /** Optional unique identifier - will auto-generate if not provided */
    id?: string
    /** The child element to wrap */
    children: React.ReactNode
}

export function SceneShortcut({
    keys,
    description,
    sceneKey,
    enabled = true,
    onAction,
    id,
    children,
}: SceneShortcutProps): JSX.Element {
    const elementRef = useRef<HTMLElement>(null)
    const { registerSceneShortcut, unregisterSceneShortcut } = useActions(sceneLogic)
    const { activeTabId, optionKeyHeld } = useValues(sceneLogic)

    // Stable ID that doesn't change on re-renders
    const shortcutId = useMemo(
        () => id || `shortcut-${sceneKey}-${keys.join('-')}-${Math.random().toString(36).substring(2, 11)}`,
        [id, sceneKey, keys]
    )

    // Stable action callback
    const stableOnAction = useCallback(onAction, [onAction])

    // Stable shortcut object
    const shortcut = useMemo(
        (): SceneShortcut => ({
            id: shortcutId,
            keys,
            description,
            enabled,
            action: stableOnAction,
            sceneKey,
            element: elementRef.current || undefined,
        }),
        [shortcutId, keys, description, enabled, stableOnAction, sceneKey]
    )

    // Register/unregister shortcut
    useEffect(() => {
        if (!activeTabId) {
            return
        }

        registerSceneShortcut(activeTabId, shortcut)

        return () => {
            unregisterSceneShortcut(activeTabId, shortcutId)
        }
    }, [activeTabId, shortcut, shortcutId, registerSceneShortcut, unregisterSceneShortcut])

    return (
        <div className="relative inline-block">
            {React.cloneElement(children as React.ReactElement, {
                ref: elementRef,
            })}
            {optionKeyHeld && enabled && (
                <div className="absolute left-0 top-0 transform -translate-x-1/2 -translate-y-1/2 z-50">
                    <div className="bg-surface-secondary border border-border rounded px-px py-px shadow-md">
                        <KeyboardShortcut {...Object.fromEntries(keys.map((key) => [key, true]))} className="text-xs" />
                    </div>
                </div>
            )}
        </div>
    )
}
