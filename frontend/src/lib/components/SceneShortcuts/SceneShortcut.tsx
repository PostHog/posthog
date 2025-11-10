import { useActions, useValues } from 'kea'
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { Tooltip } from '@posthog/lemon-ui'

import { sceneLogic } from 'scenes/sceneLogic'
import { Scene } from 'scenes/sceneTypes'

import { KeyboardShortcut } from '~/layout/navigation-3000/components/KeyboardShortcut'
import { HotKeyOrModifier } from '~/types'

import { sceneShortcutLogic } from './sceneShortcutLogic'

interface BaseShortcut {
    /** Array of keys that make up the shortcut (e.g., ['command', 'e']) */
    keys: HotKeyOrModifier[]
    /** Description of what this shortcut does */
    description: string
    /** Scene this shortcut belongs to */
    sceneKey?: Scene
    /** Whether the shortcut is currently enabled */
    enabled?: boolean
    /** Whether the shortcut is currently in active state (required for toggle shortcuts) */
    active?: boolean
    /** Whether the action palette should close when this action is triggered @default true */
    closeActionPaletteOnAction?: boolean
    /** Type of shortcut for icon display */
    type?: 'action' | 'toggle' | 'link'
    /** Order for sorting within groups. Lower numbers appear first. -1 = first, 0 = default, 1+ = later */
    order?: number
}

export interface SceneShortcut extends BaseShortcut {
    id: string
    enabled: boolean
    action: () => void
    element?: HTMLElement
    actionToggle?: (active: boolean) => void
}

export interface SceneShortcutProps extends BaseShortcut {
    /** The action to perform when the shortcut is triggered */
    onAction?: () => void
    /** Toggle action that receives the current active state - requires active prop to be set */
    onActionToggle?: (active: boolean) => void
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
    onActionToggle,
    active,
    id,
    children,
    closeActionPaletteOnAction = true,
    type,
    order,
}: SceneShortcutProps): JSX.Element {
    const elementRef = useRef<HTMLElement>(null)
    const { registerSceneShortcut, unregisterSceneShortcut } = useActions(sceneShortcutLogic)
    const { activeTabId } = useValues(sceneLogic)
    const { optionKeyHeld } = useValues(sceneShortcutLogic)
    const [showTooltip, setShowTooltip] = useState(false)

    // Stable ID that doesn't change on re-renders
    const shortcutId = useMemo(
        () => id || `shortcut-${sceneKey}-${keys.join('-')}-${Math.random().toString(36).substring(2, 11)}`,
        [id, sceneKey, keys]
    )

    // Stable action callback with toggle logic
    const stableOnAction = useCallback(() => {
        if (onActionToggle && active !== undefined) {
            // Toggle logic: pass current active state to the toggle function
            onActionToggle(active)
        } else if (onAction) {
            // Fallback to traditional onAction
            onAction()
        }
    }, [onAction, onActionToggle, active])

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
            closeActionPaletteOnAction,
            active,
            actionToggle: onActionToggle,
            type,
            order,
        }),
        [
            shortcutId,
            keys,
            description,
            enabled,
            stableOnAction,
            sceneKey,
            closeActionPaletteOnAction,
            active,
            onActionToggle,
            type,
            order,
        ]
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
        <div
            className="contents"
            onMouseOver={() => {
                setShowTooltip(true)
            }}
            onMouseOut={() => {
                setShowTooltip(false)
            }}
        >
            <Tooltip
                title={
                    showTooltip ? (
                        <>
                            {description}{' '}
                            <KeyboardShortcut
                                {...Object.fromEntries(keys.map((key) => [key, true]))}
                                className="text-xs"
                            />
                        </>
                    ) : undefined
                }
                visible={(optionKeyHeld || showTooltip) && enabled}
                closeDelayMs={0}
            >
                {React.cloneElement(children as React.ReactElement, {
                    ref: elementRef,
                })}
            </Tooltip>
        </div>
    )
}
