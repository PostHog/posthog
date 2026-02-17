import { actions, kea, path, reducers, selectors } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import type { sidePanelOfframpLogicType } from './sidePanelOfframpLogicType'

export const sidePanelOfframpLogic = kea<sidePanelOfframpLogicType>([
    path(['layout', 'navigation-3000', 'sidepanel', 'sidePanelOfframpLogic']),
    actions({
        showOfframpModal: true,
        dismissOfframpModal: true,
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
])
