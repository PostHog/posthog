import { actions, kea, listeners, path, reducers, selectors } from 'kea'
import posthog from 'posthog-js'

import type { sidePanelOfframpLogicType } from './sidePanelOfframpLogicType'

export const sidePanelOfframpLogic = kea<sidePanelOfframpLogicType>([
    path(['layout', 'navigation-3000', 'sidepanel', 'sidePanelOfframpLogic']),
    actions({
        showOfframpModal: true,
        hideOfframpModal: (action: 'close' | 'dismiss') => ({ action }),
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
            (s) => [s.isOfframpModalVisible],
            (isOfframpModalVisible): boolean => isOfframpModalVisible,
        ],
    }),
    listeners({
        showOfframpModal: () => {
            posthog.capture('offramp modal shown')
        },
        hideOfframpModal: ({ action }) => {
            posthog.capture('offramp modal hidden', { action })
        },
        dismissOfframpModal: () => {
            posthog.capture('offramp modal hidden', { action: 'dismiss' })
        },
    }),
])
