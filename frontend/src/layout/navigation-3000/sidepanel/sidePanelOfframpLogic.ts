import { actions, kea, listeners, path, reducers, selectors } from 'kea'
import posthog from 'posthog-js'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import type { sidePanelOfframpLogicType } from './sidePanelOfframpLogicType'

export const sidePanelOfframpLogic = kea<sidePanelOfframpLogicType>([
    path(['layout', 'navigation-3000', 'sidepanel', 'sidePanelOfframpLogic']),
    actions({
        showOfframpModal: true,
        dismissOfframpModal: (step?: number, reason?: string) => ({ step, reason }),
    }),
    reducers({
        isOfframpModalDismissed: [
            false,
            { persist: true },
            {
                dismissOfframpModal: () => true,
                showOfframpModal: () => false,
            },
        ],
    }),
    selectors({
        shouldShowOfframpModal: [
            (s) => [s.isOfframpModalDismissed, featureFlagLogic.selectors.featureFlags],
            (isOfframpModalDismissed, featureFlags): boolean =>
                !isOfframpModalDismissed && !!featureFlags[FEATURE_FLAGS.UX_REMOVE_SIDEPANEL],
        ],
    }),
    listeners({
        showOfframpModal: () => {
            posthog.capture('sidepanel offramp modal shown')
        },
        dismissOfframpModal: ({ step, reason }) => {
            posthog.capture('sidepanel offramp modal dismissed', { step, reason })
        },
    }),
])
