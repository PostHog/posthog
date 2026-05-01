import { actions, kea, path, reducers } from 'kea'
import { windowValues } from 'kea-window-values'

import type { navigationLogicType } from './navigationLogicType'

export const navigationLogic = kea<navigationLogicType>([
    path(['layout', 'navigation', 'navigationLogic']),
    actions({
        showConfigurePinnedTabsModal: true,
        hideConfigurePinnedTabsModal: true,
        showConfigurePinnedTabsTooltip: true,
        hideConfigurePinnedTabsTooltip: true,
    }),
    windowValues(() => ({
        fullscreen: (window: Window) => !!window.document.fullscreenElement,
        mobileLayout: (window: Window) => window.innerWidth < 992, // Sync width threshold with Sass variable $lg!
    })),
    reducers({
        isConfigurePinnedTabsModalOpen: [
            false,
            {
                showConfigurePinnedTabsModal: () => true,
                hideConfigurePinnedTabsModal: () => false,
            },
        ],
        isConfigurePinnedTabsTooltipVisible: [
            false,
            {
                showConfigurePinnedTabsTooltip: () => true,
                hideConfigurePinnedTabsTooltip: () => false,
            },
        ],
        isConfigurePinnedTabsTooltipDismissed: [
            false,
            { persist: true },
            {
                hideConfigurePinnedTabsTooltip: () => true,
            },
        ],
    }),
])
