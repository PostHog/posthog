import { kea } from 'kea'

import { navigation3000Logic } from '../navigation-3000/navigationLogic'
import type { panelLayoutLogicType } from './panelLayoutLogicType'

export const panelLayoutLogic = kea<panelLayoutLogicType>({
    path: ['layout', 'panel-layout', 'panelLayoutLogic'],
    connect: {
        values: [navigation3000Logic, ['mobileLayout']],
    },
    actions: {
        showLayoutNavBar: (visible: boolean) => ({ visible }),
        showLayoutPanel: (visible: boolean) => ({ visible }),
        toggleLayoutPanelPinned: (pinned: boolean) => ({ pinned }),
        // TODO: This is a temporary action to set the active navbar item
        // We should remove this once we have a proper way to handle the navbar item
        setActiveLayoutNavBarItem: (item: 'project' | 'activity') => ({ item }),
    },
    reducers: {
        isLayoutNavbarVisibleForDesktop: [
            true,
            {
                showLayoutNavBar: () => true,
                mobileLayout: () => true,
            },
        ],
        isLayoutNavbarVisibleForMobile: [
            false,
            {
                showLayoutNavBar: (_, { visible }) => visible,
                mobileLayout: () => true,
            },
        ],
        isLayoutPanelVisible: [
            false,
            {
                showLayoutPanel: (_, { visible }) => visible,
                toggleLayoutPanelPinned: (_, { pinned }) => pinned || _,
            },
        ],
        isLayoutPanelPinned: [false, { toggleLayoutPanelPinned: (_, { pinned }) => pinned }],
        activeLayoutNavBarItem: ['project', { setActiveLayoutNavBarItem: (_, { item }) => item }],
    },
})
