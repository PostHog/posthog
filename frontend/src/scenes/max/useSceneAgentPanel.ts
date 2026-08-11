import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { useAttachedContext, useWelcomeOverride } from 'products/posthog_ai/frontend/api/logics'
import { AttachedContextItem } from 'products/posthog_ai/frontend/api/types'

import { sceneAgentPanelLogic } from './sceneAgentPanelLogic'

export interface SceneAgentPanelOptions {
    /** Stable key for this scene's auto-open dismissal memory, e.g. 'workflow'. */
    sceneKey: string
    /** Context attached while the scene is mounted — the entity ref, live state, skill and tool guidance. */
    contextItems: AttachedContextItem[] | null
    /** Contextual welcome headlines for the composer's empty state; defaults apply when omitted. */
    headlines?: string[]
    /** When false, nothing is attached or opened (e.g. while the entity is still loading). Defaults to true. */
    active?: boolean
    /** Set false to attach context without auto-opening the panel. Defaults to true. */
    autoOpen?: boolean
}

/**
 * Scene-level PostHog AI integration: attaches the given context items for the lifetime of the
 * scene and auto-opens the AI side panel (subject to `sceneAgentPanelLogic`'s gates, including the
 * user's persisted per-scene dismissal). The whole integration rides
 * `sceneAgentPanelLogic.sceneIntegrationEnabled`, so nothing is attached or overridden for users
 * the rollout flag hasn't reached. Call once from a scene component.
 */
export function useSceneAgentPanel({
    sceneKey,
    contextItems,
    headlines,
    active = true,
    autoOpen = true,
}: SceneAgentPanelOptions): void {
    const { sceneIntegrationEnabled } = useValues(sceneAgentPanelLogic)
    const { sceneEntered, sceneLeft } = useActions(sceneAgentPanelLogic)
    useAttachedContext(contextItems, { active: active && sceneIntegrationEnabled })
    useWelcomeOverride(headlines ?? null, { active: active && sceneIntegrationEnabled })

    useEffect(() => {
        // Deliberately not gated on sceneIntegrationEnabled: the logic decides eligibility itself,
        // including the late-resolving flag case (scene entered before the flags response lands).
        if (!active || !autoOpen) {
            return
        }
        sceneEntered(sceneKey)
        return () => sceneLeft(sceneKey)
    }, [active, autoOpen, sceneKey, sceneEntered, sceneLeft])
}
