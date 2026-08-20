import { useValues } from 'kea'

import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { sceneLogic } from 'scenes/sceneLogic'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'

import { AiOnboarding } from 'products/posthog_ai/frontend/api/onboarding'

import { maxGlobalLogic } from '../maxGlobalLogic'
import { resolvePhaiOnboardingHost } from './phaiOnboardingHost'
import { MAX_SIDE_PANEL_ID } from './PhaiSidePanelChat'

/**
 * Decides whether the PostHog AI onboarding takeover should show, and for which composer. Lives here rather
 * than in the surface because the answer depends on the runtime toggle and the entry point, neither of which
 * `products/posthog_ai/frontend` is allowed to know about. The decision itself is in
 * `resolvePhaiOnboardingHost`, which is tested directly.
 *
 * Mounted from `GlobalModals` so the takeover can cover the whole app: it fires on the first open of the
 * runner from any entry point, and a narrow side panel must not clip it.
 */
export function MaybePhaiOnboarding(): JSX.Element | null {
    const { sceneId } = useValues(sceneLogic)
    const { receivedFeatureFlags } = useValues(featureFlagLogic)
    const { effectivePhaiView } = useValues(maxGlobalLogic)
    const { sidePanelOpen, selectedTab } = useValues(sidePanelStateLogic)

    const host = resolvePhaiOnboardingHost({
        sceneId,
        receivedFeatureFlags,
        effectivePhaiView,
        sidePanelOpen,
        selectedTab,
    })

    if (!host) {
        return null
    }

    // Both scenes run their composer under `taskTrackerSceneLogic`'s default `'scene'` key.
    return <AiOnboarding autoOpen panelId={host === 'side-panel' ? MAX_SIDE_PANEL_ID : undefined} />
}
