import { router } from 'kea-router'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { removeProjectIdIfPresent } from 'lib/utils/kea-router'
import { toolHrefForPath } from 'scenes/tools/toolsUtils'

import { initKeaTests } from '~/test/init'

import { todaySceneTabsLogic } from './todaySceneTabsLogic'
import { TODAY_RAIL_WIDTH, TODAY_SIDEBAR_MAX_WIDTH, railPaneForPath, todayShellLogic } from './todayShellLogic'

function setRailFlags({ rail = true, warehouse = false }: { rail?: boolean; warehouse?: boolean }): void {
    featureFlagLogic.mount()
    featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.TODAY_RAIL_NAV, FEATURE_FLAGS.TODAY_RAIL_WAREHOUSE], {
        [FEATURE_FLAGS.TODAY_RAIL_NAV]: rail,
        [FEATURE_FLAGS.TODAY_RAIL_WAREHOUSE]: warehouse,
    })
}

describe('todayShellLogic', () => {
    beforeEach(() => {
        initKeaTests()
    })

    test.each([
        ['/project/1/home', 'home', true],
        ['/project/1/home/reports/abc', 'home', true],
        ['/project/1/library', 'products', true],
        ['/project/1/library/feature_flag', 'products', true],
        ['/project/1/ai', 'spaces', true],
        ['/project/1/ai/history', 'spaces', true],
        ['/project/1/spaces/abc', 'spaces', true],
        ['/project/1/feature_flags/920847', 'products', true],
        ['/project/1/insights/abc', 'products', true],
        ['/project/1/feature_flags', 'products', true],
        ['/project/1/data-management/destinations', 'products', true],
        ['/project/1/sql', 'warehouse', true],
        ['/project/1/warehouse', 'warehouse', true],
        ['/project/1/data-management/sources/abc/schemas', 'warehouse', true],
        ['/project/1/data-warehouse/new-source', 'warehouse', true],
        ['/project/1/models/abc', 'warehouse', true],
        ['/project/1/notebooks', 'views', true],
        ['/project/1/warehouses', null, true],
        ['/project/1/views', 'views', true],
        ['/project/1/canvases/abc', 'views', true],
        ['/project/1/canvases/new', 'views', true],
        ['/project/1/notebooks/abc', 'views', true],
        ['/project/1/dashboard/12', 'views', true],
        ['/project/1/airplane', null, true],
        ['/project/1/homework', null, true],
        ['/project/1/sql', 'products', false],
        ['/project/1/data-management/sources/abc/schemas', 'products', false],
        ['/project/1/models/abc', 'products', false],
        ['/project/1/warehouse', null, false],
        ['/project/1/notebooks', 'views', false],
    ])('puts %s under %s with the warehouse flag %s', (pathname, pane, warehouseEnabled) => {
        expect(railPaneForPath(pathname, warehouseEnabled)).toBe(pane)
    })

    test.each([
        ['/data-management/destinations', '/data-management/destinations?tab=all'],
        ['/data-management/destinations/abc', '/data-management/destinations?tab=all'],
        ['/data-management/events', '/data-management'],
        ['/data-management-old', null],
    ])('selects the tool for %s', (path, href) => {
        const tools = [{ href: '/data-management' }, { href: '/data-management/destinations?tab=all' }]
        expect(toolHrefForPath(path, tools)).toBe(href)
    })

    test.each([
        ['home', '/home'],
        ['spaces', '/ai'],
        ['views', '/views'],
        ['products', '/tools'],
        ['warehouse', '/warehouse'],
    ] as const)('opens the %s section when its rail item is picked', (pane, pathname) => {
        setRailFlags({ warehouse: true })
        const logic = todayShellLogic()
        logic.mount()

        router.actions.push('/project/1/airplane')
        logic.actions.pickPane(pane)
        expect(removeProjectIdIfPresent(router.values.location.pathname)).toBe(pathname)
        expect(logic.values.activePane).toBe(pane)
    })

    it('keeps warehouse routes under Products while the warehouse flag is off', () => {
        setRailFlags({ warehouse: false })
        const logic = todayShellLogic()
        logic.mount()

        router.actions.push('/project/1/sql')
        expect(logic.values.todayWarehouseEnabled).toBe(false)
        expect(logic.values.activePane).toBe('products')
        expect(logic.values.sceneTabsInSidebar).toBe(false)
    })

    it('keeps the last pane open on pages that belong to no pane', () => {
        const logic = todayShellLogic()
        logic.mount()

        logic.actions.pickPane('products')
        router.actions.push('/project/1/airplane')
        expect(logic.values.activePane).toBe('products')

        router.actions.push('/project/1/ai')
        expect(logic.values.activePane).toBe('spaces')
    })

    it('sizes the left navigation from the clamped sidebar width, and from the rail alone when hidden', () => {
        const logic = todayShellLogic()
        logic.mount()

        logic.actions.setSidebarOpen(true)
        logic.actions.setSidebarWidth(10_000)
        expect(logic.values.leftNavWidth).toBe(TODAY_RAIL_WIDTH + TODAY_SIDEBAR_MAX_WIDTH)

        logic.actions.setSidebarOpen(false)
        expect(logic.values.leftNavWidth).toBe(TODAY_RAIL_WIDTH)
    })
    it('keeps the rail on narrow windows and opens the sidebar as a drawer that closes on navigation', () => {
        const originalWidth = window.innerWidth
        Object.defineProperty(window, 'innerWidth', { configurable: true, value: 800 })
        try {
            featureFlagLogic.mount()
            featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.TODAY_RAIL_NAV], {
                [FEATURE_FLAGS.TODAY_RAIL_NAV]: true,
            })
            const logic = todayShellLogic()
            logic.mount()

            expect(logic.values.todayRailEnabled).toBe(true)
            expect(logic.values.leftNavWidth).toBe(TODAY_RAIL_WIDTH)
            expect(logic.values.sidebarVisible).toBe(false)

            logic.actions.setSidebarOpen(false)
            logic.actions.pickPane('products')
            expect(logic.values.sidebarVisible).toBe(true)
            expect(logic.values.sidebarOpen).toBe(false)
            expect(logic.values.leftNavWidth).toBe(TODAY_RAIL_WIDTH)

            router.actions.push('/project/1/insights/abc')
            expect(logic.values.sidebarVisible).toBe(false)
        } finally {
            Object.defineProperty(window, 'innerWidth', { configurable: true, value: originalWidth })
        }
    })

    it('on phone widths, drops the rail width', () => {
        const originalWidth = window.innerWidth
        Object.defineProperty(window, 'innerWidth', { configurable: true, value: 390 })
        try {
            const logic = todayShellLogic()
            logic.mount()
            expect(logic.values.leftNavWidth).toBe(0)
        } finally {
            Object.defineProperty(window, 'innerWidth', { configurable: true, value: originalWidth })
        }
    })

    test.each([
        ['/project/1/ai', { task: 'task-1' }, true],
        ['/project/1/ai', { chat: 'chat-1' }, false],
        ['/project/1/ai', {}, false],
        ['/project/1/ai-observability', { task: 'task-1' }, false],
        ['/project/1/tasks', { task: 'task-1' }, false],
    ])('on phone widths, %s with %o hides the phone header: %s', (pathname, searchParams, hidden) => {
        const originalWidth = window.innerWidth
        Object.defineProperty(window, 'innerWidth', { configurable: true, value: 390 })
        try {
            featureFlagLogic.mount()
            featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.TODAY_RAIL_NAV], {
                [FEATURE_FLAGS.TODAY_RAIL_NAV]: true,
            })
            const logic = todayShellLogic()
            logic.mount()

            router.actions.push(pathname, searchParams)
            expect(logic.values.phoneHeaderHidden).toBe(hidden)
        } finally {
            Object.defineProperty(window, 'innerWidth', { configurable: true, value: originalWidth })
        }
    })

    it('on phone widths, goes back through pages and then to the pane', () => {
        const originalWidth = window.innerWidth
        Object.defineProperty(window, 'innerWidth', { configurable: true, value: 390 })
        try {
            const logic = todayShellLogic()
            logic.mount()

            logic.actions.pickPane('products')
            router.actions.push('/project/1/sql')
            expect(logic.values.phoneCanGoBack).toBe(false)
            router.actions.push('/project/1/sql?open_query=abc')
            router.actions.push('/project/1/insights/abc')
            expect(logic.values.sidebarVisible).toBe(false)
            expect(logic.values.phoneCanGoBack).toBe(true)

            logic.actions.goBackOnPhone()
            expect(router.values.location.pathname).toBe('/project/1/sql')
            expect(router.values.location.search).toBe('?open_query=abc')
            expect(logic.values.sidebarVisible).toBe(false)
            expect(logic.values.phoneCanGoBack).toBe(false)

            logic.actions.goBackOnPhone()
            expect(logic.values.sidebarVisible).toBe(true)
            expect(logic.values.activePane).toBe('products')
        } finally {
            Object.defineProperty(window, 'innerWidth', { configurable: true, value: originalWidth })
        }
    })

    it('gives a sidebar-less pane the full width without forgetting the sidebar setting', () => {
        setRailFlags({ warehouse: true })
        const logic = todayShellLogic()
        logic.mount()

        logic.actions.setSidebarOpen(false)
        logic.actions.pickPane('warehouse')
        expect(logic.values.activePane).toBe('warehouse')
        expect(logic.values.sidebarOpen).toBe(false)
        expect(logic.values.sidebarVisible).toBe(false)

        logic.actions.setSidebarOpen(true)
        logic.actions.pickPane('warehouse')
        expect(logic.values.sidebarOpen).toBe(true)
        expect(logic.values.sidebarVisible).toBe(false)
        expect(logic.values.leftNavWidth).toBe(TODAY_RAIL_WIDTH)

        router.actions.push('/project/1/airplane')
        expect(logic.values.activePane).toBe('warehouse')
        expect(logic.values.sidebarVisible).toBe(false)

        const tabsLogic = todaySceneTabsLogic()
        tabsLogic.mount()
        tabsLogic.actions.addSceneTabs()
        expect(logic.values.sidebarVisible).toBe(true)
        expect(logic.values.sidebarInContent).toBe(true)
        expect(logic.values.leftNavWidth).toBe(TODAY_RAIL_WIDTH)
        tabsLogic.actions.removeSceneTabs()
        tabsLogic.actions.releaseSceneTabs()
        expect(logic.values.sidebarVisible).toBe(false)

        logic.actions.pickPane('home')
        expect(logic.values.sidebarVisible).toBe(true)

        logic.actions.pickPane('warehouse')
        setRailFlags({ warehouse: false })
        expect(logic.values.activePane).not.toBe('warehouse')
        expect(logic.values.activePaneHasSidebar).toBe(true)
        expect(logic.values.sidebarVisible).toBe(true)
    })

    test.each([
        ['the sidebar is open on a warehouse page', '/project/1/models', true, 1024, true, true],
        ['the sidebar is closed', '/project/1/models', false, 1024, true, false],
        ['the rail flag is off', '/project/1/models', true, 1024, false, false],
        ['the page is not a warehouse page', '/project/1/insights', true, 1024, true, false],
        ['the layout is a phone', '/project/1/models', true, 390, true, false],
        ['the drawer is open on a narrow desktop', '/project/1/models', false, 900, true, true, true],
        ['the drawer is open on a phone', '/project/1/models', false, 390, true, false, true],
    ])('sceneTabsInSidebar when %s', (_name, path, sidebarOpen, width, flagOn, expected, drawerOpen = false) => {
        const originalWidth = window.innerWidth
        Object.defineProperty(window, 'innerWidth', { configurable: true, value: width })
        try {
            setRailFlags({ rail: flagOn, warehouse: true })
            const logic = todayShellLogic()
            logic.mount()
            logic.actions.setSidebarOpen(sidebarOpen)
            router.actions.push(path)
            // A location change closes the drawer, so open it after navigating.
            logic.actions.setMobileSidebarOpen(drawerOpen)
            expect(logic.values.sceneTabsInSidebar).toBe(expected)
        } finally {
            Object.defineProperty(window, 'innerWidth', { configurable: true, value: originalWidth })
        }
    })

    it('on phone widths, opens the warehouse page without a sheet, even with scene tabs mounted', () => {
        const originalWidth = window.innerWidth
        Object.defineProperty(window, 'innerWidth', { configurable: true, value: 390 })
        try {
            setRailFlags({ warehouse: true })
            const logic = todayShellLogic()
            logic.mount()

            logic.actions.pickPane('warehouse')
            expect(removeProjectIdIfPresent(router.values.location.pathname)).toBe('/warehouse')
            expect(logic.values.sidebarVisible).toBe(false)

            // Tabs mounted on a deep-linked page must not give the pane a sidebar that Back would open empty.
            const tabsLogic = todaySceneTabsLogic()
            tabsLogic.mount()
            tabsLogic.actions.addSceneTabs()
            expect(logic.values.sidebarVisible).toBe(false)

            logic.actions.setPhonePages([{ pathname: '/project/1/warehouse', url: '/project/1/warehouse' }])
            logic.actions.goBackOnPhone()
            expect(logic.values.activePane).toBe('warehouse')
            expect(logic.values.sidebarVisible).toBe(false)
        } finally {
            Object.defineProperty(window, 'innerWidth', { configurable: true, value: originalWidth })
        }
    })
})
