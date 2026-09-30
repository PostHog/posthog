import { FeatureFlagKey } from 'lib/constants'
import { FeatureFlagsSet } from 'lib/logic/featureFlagLogic'

import type { ComposerOverride } from 'products/posthog_ai/frontend/api/logics'

// pinned: URL search param for the surface a new entity opens on. A URL that says neither opens the editor.
export const EDITOR_MODE_PARAM = 'mode'
export const EDITOR_MODE_VALUE = 'editor'
export const AI_COMPOSER_MODE_VALUE = 'ai'

// pinned: URL search param naming the surface that handed a person to an AI-first page, e.g. a cross-sell dialog.
export const HANDOFF_SOURCE_PARAM = 'source'
const HANDOFF_SOURCE_PATTERN = /^[a-z0-9_-]{1,64}$/

/** The handoff source from the URL, or null when absent or not a plain identifier, so analytics stay clean. */
export function readHandoffSource(searchParams: Record<string, any>): string | null {
    const source = searchParams[HANDOFF_SOURCE_PARAM]
    return typeof source === 'string' && HANDOFF_SOURCE_PATTERN.test(source) ? source : null
}

/** Reading the flag captures `$feature_flag_called`, the experiment's exposure, so callers run this after every cheaper check. */
export function isAiFirstVariant(flagKey: FeatureFlagKey, featureFlags: FeatureFlagsSet): boolean {
    const variant = featureFlags[flagKey]
    return variant === true || variant === 'test'
}

/**
 * Whether a "new" URL asks for the AI composer and this person is on the variant that answers it.
 * `eligibleRoute` carries the surface's own checks (the route is its new route and the URL carries no
 * starting point), and it runs before the flag read so an existing entity never records an exposure.
 */
export function aiComposerAvailable(
    flagKey: FeatureFlagKey,
    featureFlags: FeatureFlagsSet,
    sceneIntegrationEnabled: boolean,
    searchParams: Record<string, any>,
    eligibleRoute: boolean
): boolean {
    return (
        sceneIntegrationEnabled &&
        eligibleRoute &&
        searchParams[EDITOR_MODE_PARAM] === AI_COMPOSER_MODE_VALUE &&
        isAiFirstVariant(flagKey, featureFlags)
    )
}

export const AI_FIRST_COMPOSER_OVERRIDE: ComposerOverride = {
    hideRepositorySelector: true,
    hideSuggestions: true,
    hideRecentTasks: true,
    // Not a takeover host, and the side panel is closed here, so nothing would receive the replay click.
    hideOnboardingReplay: true,
}
