import { actions, kea, path, reducers } from 'kea'
import { windowValues } from 'kea-window-values'

import type { navigationLogicType } from './navigationLogicType'

export const navigationLogic = kea<navigationLogicType>([
    path(['layout', 'navigation', 'navigationLogic']),
    actions({
        showConfigureHomeModal: true,
        hideConfigureHomeModal: true,
    }),
    windowValues(() => ({
        fullscreen: (window: Window) => !!window.document.fullscreenElement,
        mobileLayout: (window: Window) => window.innerWidth < 992, // Sync width threshold with Sass variable $lg!
    })),
    reducers({
        isConfigureHomeModalOpen: [
            false,
            {
                showConfigureHomeModal: () => true,
                hideConfigureHomeModal: () => false,
            },
        ],
    }),
])
