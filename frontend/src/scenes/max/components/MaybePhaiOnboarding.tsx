import { useValues } from 'kea'

import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { sceneLogic } from 'scenes/sceneLogic'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'

import { AiOnboarding } from 'products/posthog_ai/frontend/api/onboarding'

import { maxGlobalLogic } from '../maxGlobalLogic'
import { resolvePhaiOnboardingMounts } from './phaiOnboardingHost'
import { MAX_SIDE_PANEL_ID } from './PhaiSidePanelChat'

/**
 * Mounts the PostHog AI onboarding takeover for whichever composers are on screen, and decides which of them
 * may open it on its own. Lives here rather than in the surface because the answer depends on the runtime
 * toggle and the entry point, neither of which `products/posthog_ai/frontend` is allowed to know about. The
 * decision itself is in `resolvePhaiOnboardingMounts`, which is tested directly.
 *
 * Mounted from `GlobalModals` so the takeover can cover the whole app: it fires on the first open of the
 * runner from any entry point, and a narrow side panel must not clip it.
 */
export function MaybePhaiOnboarding(): JSX.Element | null {
    const { sceneId } = useValues(sceneLogic)
    const { receivedFeatureFlags } = useValues(featureFlagLogic)
    const { effectivePhaiView } = useValues(maxGlobalLogic)
    const { sidePanelOpen, selectedTab } = useValues(sidePanelStateLogic)

    const mounts = resolvePhaiOnboardingMounts({
        sceneId,
        receivedFeatureFlags,
        effectivePhaiView,
        sidePanelOpen,
        selectedTab,
    })

    if (!mounts.length) {
        return null
    }

    return (
        <>
            {mounts.map(({ host, autoOpen }) => (
                // Both scenes run their composer under `taskTrackerSceneLogic`'s default `'scene'` key.
                <AiOnboarding
                    key={host}
                    autoOpen={autoOpen}
                    panelId={host === 'side-panel' ? MAX_SIDE_PANEL_ID : undefined}
                />
            ))}
        </>
    )
}
