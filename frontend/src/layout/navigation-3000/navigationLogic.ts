import { actions, events, kea, listeners, path, reducers, selectors } from 'kea'
import { subscriptions } from 'kea-subscriptions'
import { SidebarNavbarItem } from './types'

import type { navigation3000LogicType } from './navigationLogicType'
import { NAVBAR_ITEM_ID_TO_ITEM } from './sidebars/navbarItems'
import { Scene } from 'scenes/sceneTypes'

const MINIMUM_SIDEBAR_WIDTH_PX: number = 192
const DEFAULT_SIDEBAR_WIDTH_PX: number = 288
const MAXIMUM_SIDEBAR_WIDTH_PX: number = 1024
const MAXIMUM_SIDEBAR_WIDTH_PERCENTAGE: number = 50
export const SIDEBAR_SEARCH_INPUT_ID = 'sidebar-search'

export const navigation3000Logic = kea<navigation3000LogicType>([
    path(['layout', 'navigation-3000', 'navigationLogic']),
    actions({
        hideSidebar: true,
        showSidebar: (newNavbarItemId?: string) => ({ newNavbarItemId }),
        toggleSidebar: true,
        setSidebarWidth: (width: number) => ({ width }),
        setSidebarOverslide: (overslide: number) => ({ overslide }),
        syncSidebarWidthWithMouseMove: (delta: number) => ({ delta }),
        syncSidebarWidthWithViewport: true,
        beginResize: true,
        endResize: true,
        acknowledgeSidebarKeyboardShortcut: true,
        setIsSearchShown: (isSearchShown: boolean) => ({ isSearchShown }),
        setSearchTerm: (searchTerm: string) => ({ searchTerm }),
    }),
    reducers({
        isSidebarShown: [
            true,
            {
                persist: true,
            },
            {
                hideSidebar: () => false,
                showSidebar: () => true,
                toggleSidebar: (isSidebarShown) => !isSidebarShown,
            },
        ],
        sidebarWidth: [
            DEFAULT_SIDEBAR_WIDTH_PX,
            { persist: true },
            {
                setSidebarWidth: (_, { width }) => width,
            },
        ],
        sidebarOverslide: [
            // Overslide is how far beyond the min/max sidebar width the cursor has moved
            0,
            { persist: true },
            {
                setSidebarOverslide: (_, { overslide }) => overslide,
            },
        ],
        isResizeInProgress: [
            false,
            {
                beginResize: () => true,
                endResize: () => false,
            },
        ],
        isSidebarKeyboardShortcutAcknowledged: [
            false,
            {
                persist: true,
            },
            {
                acknowledgeSidebarKeyboardShortcut: () => true,
            },
        ],
        activeNavbarItemId: [
            Scene.Dashboards as string,
            {
                persist: true,
            },
            {
                showSidebar: (state, { newNavbarItemId }) => newNavbarItemId || state,
            },
        ],
        isSearchShown: [
            false,
            {
                setIsSearchShown: (_, { isSearchShown }) => isSearchShown,
            },
        ],
        internalSearchTerm: [
            // Do not reference this outside of this file
            // `searchTerm` is the outwards-facing value, as it's made empty when search is hidden
            '',
            {
                setSearchTerm: (_, { searchTerm }) => searchTerm,
            },
        ],
    }),
    listeners(({ actions, values }) => ({
        syncSidebarWidthWithMouseMove: ({ delta }) => {
            const newWidthRaw = values.sidebarWidth + values.sidebarOverslide + delta
            let newWidth = newWidthRaw
            if (newWidth < MINIMUM_SIDEBAR_WIDTH_PX) {
                newWidth = MINIMUM_SIDEBAR_WIDTH_PX
            } else if (newWidth > MAXIMUM_SIDEBAR_WIDTH_PX) {
                newWidth = MAXIMUM_SIDEBAR_WIDTH_PX
            }
            if (newWidth > window.innerWidth * (MAXIMUM_SIDEBAR_WIDTH_PERCENTAGE / 100)) {
                newWidth = window.innerWidth * (MAXIMUM_SIDEBAR_WIDTH_PERCENTAGE / 100)
            }
            actions.setSidebarWidth(newWidth)
            actions.setSidebarOverslide(newWidthRaw - newWidth)
            if (newWidthRaw < MINIMUM_SIDEBAR_WIDTH_PX / 2) {
                if (values.isSidebarShown) {
                    actions.hideSidebar()
                }
            } else {
                if (!values.isSidebarShown) {
                    actions.showSidebar()
                }
            }
        },
        syncSidebarWidthWithViewport: () => {
            if (values.sidebarWidth > window.innerWidth * (MAXIMUM_SIDEBAR_WIDTH_PERCENTAGE / 100)) {
                // Clamp
                actions.setSidebarWidth(window.innerWidth * (MAXIMUM_SIDEBAR_WIDTH_PERCENTAGE / 100))
            }
        },
        endResize: () => {
            actions.setSidebarOverslide(values.isSidebarShown ? 0 : -MINIMUM_SIDEBAR_WIDTH_PX)
        },
        toggleSidebar: () => {
            actions.endResize()
        },
    })),
    selectors({
        sidebarOverslideDirection: [
            (s) => [s.sidebarOverslide],
            (sidebarOverslide): 'min' | 'max' | null => {
                if (sidebarOverslide < 0) {
                    return 'min'
                } else if (sidebarOverslide > 0) {
                    return 'max'
                } else {
                    return null
                }
            },
        ],
        activeNavbarItem: [
            (s) => [s.activeNavbarItemId],
            (activeNavbarItemId): SidebarNavbarItem => {
                return NAVBAR_ITEM_ID_TO_ITEM[activeNavbarItemId] as SidebarNavbarItem
            },
        ],
        searchTerm: [
            (s) => [s.internalSearchTerm, s.isSearchShown],
            (internalSearchTerm, isSearchShown): string => {
                return isSearchShown ? internalSearchTerm : ''
            },
        ],
    }),
    subscriptions(({ cache, actions }) => ({
        isResizeInProgress: (isResizeInProgress) => {
            if (isResizeInProgress) {
                cache.onMouseMove = (e: MouseEvent): void => actions.syncSidebarWidthWithMouseMove(e.movementX)
                cache.onMouseUp = (e: MouseEvent): void => {
                    if (e.button === 0) {
                        actions.endResize()
                    }
                }
                document.addEventListener('mousemove', cache.onMouseMove)
                document.addEventListener('mouseup', cache.onMouseUp)
                return () => {}
            } else {
                document.removeEventListener('mousemove', cache.onMouseMove)
                document.removeEventListener('mouseup', cache.onMouseUp)
            }
        },
    })),
    events(({ actions, cache }) => ({
        afterMount: () => {
            cache.onResize = () => actions.syncSidebarWidthWithViewport()
            cache.onKeyDown = (e: KeyboardEvent) => {
                if (e.key === 'b' && (e.metaKey || e.ctrlKey)) {
                    actions.toggleSidebar()
                    e.preventDefault()
                }
                if (e.key === 'f' && e.shiftKey && (e.metaKey || e.ctrlKey)) {
                    actions.setIsSearchShown(true)
                    document.getElementById(SIDEBAR_SEARCH_INPUT_ID)?.focus()
                    e.preventDefault()
                }
            }
            window.addEventListener('resize', cache.onResize)
            window.addEventListener('keydown', cache.onKeyDown)
        },
        beforeUnmount: () => {
            window.removeEventListener('resize', cache.onResize)
            window.removeEventListener('resize', cache.onKeyDown)
        },
    })),
])
