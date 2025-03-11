import { kea } from 'kea'

import { navigation3000Logic } from '../navigation-3000/navigationLogic'
import type { projectPanelLayoutLogicType } from './projectPanelLayoutLogicType'

export const projectPanelLayoutLogic = kea<projectPanelLayoutLogicType>({
    path: ['layout', 'project-panel-layout', 'projectPanelLayoutLogic'],
    connect: {
        values: [navigation3000Logic, ['mobileLayout']],
    },
    actions: {
        showNavBar: (visible: boolean) => ({ visible }),
        togglePanelVisible: (visible: boolean) => ({ visible }),
        togglePanelPinned: (pinned: boolean) => ({ pinned }),
        setActiveNavBarItem: (item: 'project' | 'activity') => ({ item }),
    },
    reducers: {
        isNavbarVisibleDesktop: [
            true,
            {
                showNavBar: () => true,
                mobileLayout: () => true,
            },
        ],
        isNavbarVisibleMobile: [
            false,
            {
                showNavBar: (_, { visible }) => visible,
                mobileLayout: () => true,
            },
        ],
        isPanelVisible: [
            false,
            {
                togglePanelVisible: (_, { visible }) => visible,
                togglePanelPinned: (_, { pinned }) => pinned || _,
            },
        ],
        isPanelPinned: [false, { togglePanelPinned: (_, { pinned }) => pinned }],
        activeNavBarItem: ['project', { setActiveNavBarItem: (_, { item }) => item }],
    },
})
