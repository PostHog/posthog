import { Scene } from 'scenes/sceneTypes'

import { SidePanelTab } from '~/types'

import type { PhaiViewMode } from '../maxGlobalLogic'

/** The composer a takeover targets. */
export type PhaiOnboardingHost = 'scene' | 'side-panel'

export interface PhaiOnboardingMount {
    host: PhaiOnboardingHost
    /** Whether this surface may open the takeover on its own, rather than only through the replay button. */
    autoOpen: boolean
}

export interface PhaiOnboardingHostInput {
    sceneId: string | null
    receivedFeatureFlags: boolean
    effectivePhaiView: PhaiViewMode
    sidePanelOpen: boolean
    selectedTab: SidePanelTab | null
}

/** The surface that may open the takeover by itself, on a first open of the new PostHog AI. */
function resolveAutoOpenHost({
    sceneId,
    receivedFeatureFlags,
    effectivePhaiView,
    sidePanelOpen,
    selectedTab,
}: PhaiOnboardingHostInput): PhaiOnboardingHost | null {
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

/**
 * Every takeover the current surfaces need. A surface belongs here whenever it renders the runner's
 * composer, because the composer carries the replay button — leaving one out would show a button that opens
 * nothing. Only a first open of the new PostHog AI opens the takeover by itself; `/tasks` mounts it purely
 * so its replay button works.
 */
export function resolvePhaiOnboardingMounts(input: PhaiOnboardingHostInput): PhaiOnboardingMount[] {
    const mounts: PhaiOnboardingMount[] = []

    const autoOpenHost = resolveAutoOpenHost(input)
    if (autoOpenHost) {
        mounts.push({ host: autoOpenHost, autoOpen: true })
    }

    // `/tasks` reaches everyone who can open the scene, whatever their PostHog AI view mode, so a takeover
    // opening there wouldn't line up with a first look at the new PostHog AI. It waits for the replay button.
    if (input.sceneId === Scene.TaskTracker && autoOpenHost !== 'scene') {
        mounts.push({ host: 'scene', autoOpen: false })
    }

    return mounts
}
