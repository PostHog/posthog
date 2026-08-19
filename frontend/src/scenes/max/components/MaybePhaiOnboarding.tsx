import { useValues } from 'kea'

import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { sceneLogic } from 'scenes/sceneLogic'
import { Scene } from 'scenes/sceneTypes'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { SidePanelTab } from '~/types'

import { AiOnboarding } from 'products/posthog_ai/frontend/api/onboarding'

import { maxGlobalLogic } from '../maxGlobalLogic'
import { MAX_SIDE_PANEL_ID } from './PhaiSidePanelChat'

/**
 * Decides whether the PostHog AI onboarding takeover should show, and for which composer. Lives here rather
 * than in the surface because the answer depends on the runtime toggle and the entry point, neither of which
 * `products/posthog_ai/frontend` is allowed to know about.
 *
 * Mounted from `GlobalModals` so the takeover can cover the whole app: it fires on the first open of the new
 * PostHog AI from either entry point, and a narrow side panel must not clip it.
 */
export function MaybePhaiOnboarding(): JSX.Element | null {
    const { sceneId } = useValues(sceneLogic)
    const { receivedFeatureFlags } = useValues(featureFlagLogic)
    const { effectivePhaiView } = useValues(maxGlobalLogic)
    const { sidePanelOpen, selectedTab } = useValues(sidePanelStateLogic)

    // Flags re-resolve during a session (identify, reloadFeatureFlags). Acting before they land would let a
    // dismissal write the "seen" flag for a user who never saw the new surface at all.
    if (!receivedFeatureFlags || effectivePhaiView !== 'new') {
        return null
    }

    const inSidePanel = sidePanelOpen && selectedTab === SidePanelTab.Max
    const onAiScene = sceneId === Scene.Max
    if (!inSidePanel && !onAiScene) {
        return null
    }

    // The scene wins when both are open: it's the surface the user is looking at, and it's where a chosen
    // starter prompt should land.
    return <AiOnboarding autoOpen panelId={onAiScene ? undefined : MAX_SIDE_PANEL_ID} />
}
