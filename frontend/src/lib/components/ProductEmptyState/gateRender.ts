/**
 * What `ProductEmptyStateGate` decides, kept out of the component because the gate is a lazy chunk
 * and the surfaces that ask the same question are in the eager graph.
 */

import type { FeatureFlagsSet } from 'lib/logic/featureFlagLogic'

import type {
    GatedScene,
    ProductEmptyStateConfig,
    ProductEmptyStateMode,
    ProductSetupStatus,
    SceneProductEmptyState,
} from './types'

/**
 * Search param that puts the setup screen on a scene that already has data, so anyone can
 * review an empty state without emptying a project. `?empty_state=1` shows the `needs-setup`
 * screen, `?empty_state=waiting-for-data` shows the other mode, and dropping the param
 * returns the real scene.
 */
export const EMPTY_STATE_PARAM = 'empty_state'

export function forcedModeFromParam(value: unknown): ProductEmptyStateMode | null {
    if (value === 'waiting-for-data') {
        return 'waiting-for-data'
    }
    // kea-router parses search params before we see them, so `?empty_state=1` arrives as the
    // number 1 and a bare `?empty_state` as null. Match those forms exactly rather than any
    // truthy value, so a param we don't recognize leaves the real scene alone.
    if (value === null || value === 1 || value === true || value === '1' || value === 'true') {
        return 'needs-setup'
    }
    return null
}

function coversCurrentSurface(
    gated: GatedScene,
    activeSceneId: string | null,
    params: Record<string, string | undefined>
): boolean {
    if (typeof gated === 'string') {
        return gated === activeSceneId
    }
    return gated.scene === activeSceneId && gated.tabs.includes(params.tab)
}

export type ProductEmptyStateGateActivation = 'off' | 'awaiting-flags' | 'on'

/** What a gated scene puts on screen. */
export type ProductEmptyStateGateRender = 'scene' | 'setup' | 'loading'

export interface ProductEmptyStateGateSurface {
    emptyState: SceneProductEmptyState
    activeSceneId: string | null
    params: Record<string, string | undefined>
    featureFlags: FeatureFlagsSet
    receivedFeatureFlags: boolean
    forcedMode: ProductEmptyStateMode | null
}

export interface ProductEmptyStateGateStatus {
    config: ProductEmptyStateConfig
    forcedMode: ProductEmptyStateMode | null
    status: ProductSetupStatus
    skipped: boolean
}

export function productEmptyStateGateActivation({
    emptyState,
    activeSceneId,
    params,
    featureFlags,
    receivedFeatureFlags,
    forcedMode,
}: ProductEmptyStateGateSurface): ProductEmptyStateGateActivation {
    if (emptyState.featureFlag && !featureFlags[emptyState.featureFlag]) {
        return 'off'
    }
    if (emptyState.scenes && !emptyState.scenes.some((gated) => coversCurrentSurface(gated, activeSceneId, params))) {
        return 'off'
    }
    if (emptyState.bypassFeatureFlag && !forcedMode) {
        if (!receivedFeatureFlags) {
            return 'awaiting-flags'
        }
        if (featureFlags[emptyState.bypassFeatureFlag]) {
            return 'off'
        }
    }
    return 'on'
}

export function activeProductEmptyStateGateRender({
    config,
    forcedMode,
    status,
    skipped,
}: ProductEmptyStateGateStatus): ProductEmptyStateGateRender {
    // Forcing wins over skip, over the detected status, and over detection still loading.
    // The whole point is to see the screen on a project that would never show it on its own.
    if (forcedMode) {
        return 'setup'
    }
    // A lingering local skip is ignored for non-skippable products (the button may have been
    // shown before the product opted out of skipping).
    if (skipped && config.skippable !== false) {
        return 'scene'
    }
    if (status === 'loading') {
        return 'loading'
    }
    return status === 'needs-setup' || status === 'waiting-for-data' ? 'setup' : 'scene'
}

export function productEmptyStateGateRender(
    surface: ProductEmptyStateGateSurface & Omit<ProductEmptyStateGateStatus, 'config'>
): ProductEmptyStateGateRender {
    const activation = productEmptyStateGateActivation(surface)
    if (activation === 'off') {
        return 'scene'
    }
    if (activation === 'awaiting-flags') {
        return 'loading'
    }
    return activeProductEmptyStateGateRender({ ...surface, config: surface.emptyState.config })
}
