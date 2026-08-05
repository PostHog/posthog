import { useActions } from 'kea'
import { useEffect } from 'react'

import { useAttachedContext } from 'products/posthog_ai/frontend/api/logics'
import { AttachedContextItem } from 'products/posthog_ai/frontend/api/types'

import { sceneAgentPanelLogic } from './sceneAgentPanelLogic'

export interface SceneAgentPanelOptions {
    /** Stable key for this scene's auto-open dismissal memory, e.g. 'workflow'. */
    sceneKey: string
    /** Context attached while the scene is mounted — the entity ref, live state, skill and tool guidance. */
    contextItems: AttachedContextItem[] | null
    /** When false, nothing is attached or opened (e.g. while the entity is still loading). Defaults to true. */
    active?: boolean
    /** Set false to attach context without auto-opening the panel. Defaults to true. */
    autoOpen?: boolean
}

/**
 * Scene-level PostHog AI integration: attaches the given context items for the lifetime of the
 * scene and auto-opens the AI side panel (subject to `sceneAgentPanelLogic`'s gates, including the
 * user's persisted per-scene dismissal). Call once from a scene component.
 */
export function useSceneAgentPanel({
    sceneKey,
    contextItems,
    active = true,
    autoOpen = true,
}: SceneAgentPanelOptions): void {
    useAttachedContext(contextItems, { active })
    const { sceneEntered, sceneLeft } = useActions(sceneAgentPanelLogic)

    useEffect(() => {
        if (!active || !autoOpen) {
            return
        }
        sceneEntered(sceneKey)
        return () => sceneLeft(sceneKey)
    }, [active, autoOpen, sceneKey, sceneEntered, sceneLeft])
}
