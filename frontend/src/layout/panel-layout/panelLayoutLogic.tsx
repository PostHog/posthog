import { actions, connect, kea, path, reducers, selectors } from 'kea'
import { LemonTreeRef, TreeMode } from 'lib/lemon-ui/LemonTree/LemonTree'

import { navigation3000Logic } from '../navigation-3000/navigationLogic'
import type { panelLayoutLogicType } from './panelLayoutLogicType'

export type PanelLayoutNavIdentifier = 'Project' | 'Recent' | 'Products' | 'Games' | 'Shortcuts'
export type PanelLayoutTreeRef = React.RefObject<LemonTreeRef> | null
export type PanelLayoutMainContentRef = React.RefObject<HTMLElement> | null
export const PANEL_LAYOUT_DEFAULT_WIDTH: number = 320

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
        setPanelTreeRef: (ref: PanelLayoutTreeRef) => ({ ref }),
        setMainContentRef: (ref: PanelLayoutMainContentRef) => ({ ref }),
        toggleLayoutNavCollapsed: (override?: boolean) => ({ override }),
        setVisibleSideAction: (sideAction: string) => ({ sideAction }),
        setProjectTreeMode: (mode: TreeMode) => ({ mode }),
        setPanelWidth: (width: number) => ({ width }),
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
            true,
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
        visibleSideAction: [
            '',
            {
                setVisibleSideAction: (_, { sideAction }) => sideAction,
            },
        ],
        projectTreeMode: [
            'tree' as TreeMode,
            {
                setProjectTreeMode: (_, { mode }) => mode,
            },
        ],
        panelWidth: [
            PANEL_LAYOUT_DEFAULT_WIDTH,
            { persist: true },
            {
                setPanelWidth: (_, { width }) => width,
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
