import { actions, kea, path, reducers, selectors } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import type { sidePanelOfframpLogicType } from './sidePanelOfframpLogicType'

export const sidePanelOfframpLogic = kea<sidePanelOfframpLogicType>([
    path(['layout', 'navigation-3000', 'sidepanel', 'sidePanelOfframpLogic']),
    actions({
        showOfframpModal: true,
        hideOfframpModal: true,
        dismissOfframpModal: true,
    }),
    reducers({
        isOfframpModalVisible: [
            false,
            {
                showOfframpModal: () => true,
                hideOfframpModal: () => false,
                dismissOfframpModal: () => false,
            },
        ],
        isSceneTabsOfframpDismissed: [
            false,
            { persist: true },
            {
                dismissOfframpModal: () => true,
            },
        ],
    }),
    selectors({
        shouldShowOfframpModal: [
            (s) => [s.isOfframpModalVisible, featureFlagLogic.selectors.featureFlags],
            (isOfframpModalVisible, featureFlags): boolean =>
                isOfframpModalVisible && !!featureFlags[FEATURE_FLAGS.UX_REMOVE_SIDEPANEL],
        ],
    }),
])
