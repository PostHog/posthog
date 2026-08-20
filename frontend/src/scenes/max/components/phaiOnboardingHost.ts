import { Scene } from 'scenes/sceneTypes'

import { SidePanelTab } from '~/types'

import type { PhaiViewMode } from '../maxGlobalLogic'

/** The composer the takeover should target, or `null` when the user isn't on a surface that runs one. */
export type PhaiOnboardingHost = 'scene' | 'side-panel' | null

export interface PhaiOnboardingHostInput {
    sceneId: string | null
    receivedFeatureFlags: boolean
    effectivePhaiView: PhaiViewMode
    sidePanelOpen: boolean
    selectedTab: SidePanelTab | null
}

/**
 * Where the PostHog AI onboarding takeover may open. Every surface that renders the runner's composer
 * belongs here: the composer carries the replay button, which reopens the takeover, so a surface left out
 * would show a button that opens nothing.
 */
export function resolvePhaiOnboardingHost({
    sceneId,
    receivedFeatureFlags,
    effectivePhaiView,
    sidePanelOpen,
    selectedTab,
}: PhaiOnboardingHostInput): PhaiOnboardingHost {
    // `/tasks` renders the runner for everyone who can reach the scene, with no runtime toggle in play, so
    // the takeover follows the scene rather than the PostHog AI view mode.
    if (sceneId === Scene.TaskTracker) {
        return 'scene'
    }

    // Flags re-resolve during a session (identify, reloadFeatureFlags). Acting before they land would let a
    // dismissal write the "seen" flag for a user who never saw the new surface at all.
    if (!receivedFeatureFlags || effectivePhaiView !== 'new') {
        return null
    }

    // A scene wins when the side panel is open as well: it's the surface the user is looking at, and it's
    // where a chosen starter prompt should land.
    if (sceneId === Scene.Max) {
        return 'scene'
    }

    if (sidePanelOpen && selectedTab === SidePanelTab.Max) {
        return 'side-panel'
    }

    return null
}
