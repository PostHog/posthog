import { actions, connect, kea, path, reducers, selectors } from 'kea'
import { LemonTreeRef } from 'lib/lemon-ui/LemonTree/LemonTree'

import { navigation3000Logic } from '../navigation-3000/navigationLogic'
import type { panelLayoutLogicType } from './panelLayoutLogicType'

export type PanelLayoutNavIdentifier = 'Project' // Add more identifiers here for more panels
export type PanelLayoutTreeRef = React.RefObject<LemonTreeRef> | null
export type PanelLayoutMainContentRef = React.RefObject<HTMLElement> | null

export const panelLayoutLogic = kea<panelLayoutLogicType>([
    path(['layout', 'panel-layout', 'panelLayoutLogic']),
    connect(() => ({
        values: [navigation3000Logic, ['mobileLayout']],
    })),
    actions({
        showLayoutNavBar: (visible: boolean) => ({ visible }),
        showLayoutPanel: (visible: boolean) => ({ visible }),
        toggleLayoutPanelPinned: (pinned: boolean) => ({ pinned }),
        // TODO: This is a temporary action to set the active navbar item
        // We should remove this once we have a proper way to handle the navbar item
        setActivePanelIdentifier: (identifier: PanelLayoutNavIdentifier) => ({ identifier }),
        clearActivePanelIdentifier: true,
        setSearchTerm: (searchTerm: string) => ({ searchTerm }),
        clearSearch: true,
        setPanelTreeRef: (ref: PanelLayoutTreeRef) => ({ ref }),
        setMainContentRef: (ref: PanelLayoutMainContentRef) => ({ ref }),
        toggleLayoutNavCollapsed: (override?: boolean) => ({ override }),
    }),
    reducers({
        isLayoutNavbarVisibleForDesktop: [
            true,
            { persist: true },
            {
                showLayoutNavBar: (_, { visible }) => visible,
                mobileLayout: () => false,
            },
        ],
        isLayoutNavbarVisibleForMobile: [
            false,
            {
                showLayoutNavBar: (_, { visible }) => visible,
                mobileLayout: () => true,
            },
        ],
        isLayoutPanelCloseable: [
            true,
            {
                showLayoutPanel: () => true,
                toggleLayoutPanelPinned: () => false,
            },
        ],
        isLayoutNavbarVisible: [
            false,
            { persist: true },
            {
                showLayoutNavBar: (_, { visible }) => visible,
            },
        ],
        isLayoutPanelVisible: [
            false,
            { persist: true },
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
        activePanelIdentifier: [
            '',
            { persist: true },
            {
                setActivePanelIdentifier: (_, { identifier }) => identifier,
                clearActivePanelIdentifier: () => '',
            },
        ],
        searchTerm: [
            '',
            {
                setSearchTerm: (_, { searchTerm }) => searchTerm,
                clearSearch: () => '',
            },
        ],
        panelTreeRef: [
            null as PanelLayoutTreeRef,
            {
                setPanelTreeRef: (_, { ref }) => ref,
            },
        ],
        mainContentRef: [
            null as PanelLayoutMainContentRef,
            {
                setMainContentRef: (_, { ref }) => ref,
            },
        ],
        isLayoutNavCollapsedDesktop: [
            false,
            { persist: true },
            {
                toggleLayoutNavCollapsed: (state, { override }) => override ?? !state,
            },
        ],
    }),
    selectors({
        isLayoutNavCollapsed: [
            (s) => [s.isLayoutNavCollapsedDesktop, s.mobileLayout],
            (isLayoutNavCollapsedDesktop, mobileLayout): boolean => !mobileLayout && isLayoutNavCollapsedDesktop,
        ],
    }),
])
