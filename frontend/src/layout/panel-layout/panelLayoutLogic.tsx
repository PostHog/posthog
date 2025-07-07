import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { LemonTreeRef } from 'lib/lemon-ui/LemonTree/LemonTree'

import { navigation3000Logic } from '../navigation-3000/navigationLogic'
import type { panelLayoutLogicType } from './panelLayoutLogicType'

export type PanelLayoutNavIdentifier =
    | 'Project'
    | 'Products'
    | 'People'
    | 'Games'
    | 'Shortcuts'
    | 'DataManagement'
    | 'Database'
export type PanelLayoutTreeRef = React.RefObject<LemonTreeRef> | null
export type PanelLayoutMainContentRef = React.RefObject<HTMLElement> | null
export const PANEL_LAYOUT_DEFAULT_WIDTH: number = 245
export const PANEL_LAYOUT_MIN_WIDTH: number = 160

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
        setPanelWidth: (width: number) => ({ width }),
        setPanelIsResizing: (isResizing: boolean) => ({ isResizing }),
        setPanelWillHide: (willHide: boolean) => ({ willHide }),
        resetPanelLayout: (keyboardAction: boolean) => ({ keyboardAction }),
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
        panelWidth: [
            PANEL_LAYOUT_DEFAULT_WIDTH,
            { persist: true, prefix: '2', separator: '.' },
            {
                setPanelWidth: (_, { width }) => width,
            },
        ],
        panelIsResizing: [
            false,
            {
                setPanelIsResizing: (_, { isResizing }) => isResizing,
            },
        ],
        panelWillHide: [
            false,
            {
                showLayoutPanel: (state, { visible }) => (visible ? false : state),
                setPanelWidth: (_, { width }) => width <= PANEL_LAYOUT_MIN_WIDTH - 1,
            },
        ],
    }),
    listeners(({ actions, values }) => ({
        setPanelIsResizing: ({ isResizing }) => {
            // If we're not resizing and the panel is at or below the minimum width, hide it
            if (!isResizing && values.panelWidth <= PANEL_LAYOUT_MIN_WIDTH - 1) {
                actions.showLayoutPanel(false)
                actions.clearActivePanelIdentifier()
                actions.setPanelWidth(PANEL_LAYOUT_DEFAULT_WIDTH)
            }
        },
        resetPanelLayout: ({ keyboardAction = false }) => {
            // Hide the panel if it's not pinned and clear active panel identifier
            if (!values.isLayoutPanelPinned) {
                actions.clearActivePanelIdentifier()
                actions.showLayoutPanel(false)
            }
            // Hide the navbar if it's mobile and navbar is visible (which is an overlay on mobile)
            if (values.mobileLayout && values.isLayoutNavbarVisible) {
                actions.showLayoutNavBar(false)
            }
            // Focus the main content if it's a keyboard action
            if (keyboardAction && values.mainContentRef?.current) {
                values.mainContentRef?.current?.focus()
            }
        },
    })),
    selectors({
        isLayoutNavCollapsed: [
            (s) => [s.isLayoutNavCollapsedDesktop, s.mobileLayout],
            (isLayoutNavCollapsedDesktop, mobileLayout): boolean => !mobileLayout && isLayoutNavCollapsedDesktop,
        ],
    }),
])
