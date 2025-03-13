import { kea } from 'kea'
import { LemonTreeRef } from 'lib/lemon-ui/LemonTree/LemonTree'

import { navigation3000Logic } from '../navigation-3000/navigationLogic'
import type { panelLayoutLogicType } from './panelLayoutLogicType'

export type PanelLayoutNavItem = 'project' | 'activity' | 'persons'

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
        setActiveLayoutNavBarItem: (item: PanelLayoutNavItem) => ({ item }),
        setSearchTerm: (searchTerm: string) => ({ searchTerm }),
        clearSearch: true,
        setPanelTreeRef: (ref: React.RefObject<LemonTreeRef>) => ({ ref }),
    },
    reducers: {
        isLayoutNavbarVisibleForDesktop: [
            true,
            {
                showLayoutNavBar: (_, { visible }) => visible,
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
        isLayoutPanelPinned: [
            false,
            { persist: true },
            {
                toggleLayoutPanelPinned: (_, { pinned }) => pinned,
            },
        ],
        activeLayoutNavBarItem: ['', { setActiveLayoutNavBarItem: (_, { item }) => item }],
        searchTerm: [
            '',
            {
                setSearchTerm: (_, { searchTerm }) => searchTerm,
                clearSearch: () => '',
            },
        ],
        panelTreeRef: [
            null,
            {
                setPanelTreeRef: (_: unknown, { ref }: { ref: React.RefObject<LemonTreeRef> }) => ref as any,
            },
        ] as any,
    },
})
