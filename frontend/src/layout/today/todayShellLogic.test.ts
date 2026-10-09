import { router } from 'kea-router'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { removeProjectIdIfPresent } from 'lib/utils/kea-router'
import {
    getToolSourceItems,
    isToolItem,
    libraryRowProductLabels,
    toolHrefForPath,
    toolLabel,
} from 'scenes/tools/toolsUtils'

import { initKeaTests } from '~/test/init'

import { TODAY_RAIL_WIDTH, TODAY_SIDEBAR_MAX_WIDTH, railPaneForPath, todayShellLogic } from './todayShellLogic'

describe('todayShellLogic', () => {
    beforeEach(() => {
        initKeaTests()
    })

    test.each([
        ['/project/1/home', 'home'],
        ['/project/1/home/reports/abc', 'home'],
        ['/project/1/library', 'products'],
        ['/project/1/library/feature_flag', 'products'],
        ['/project/1/ai', 'spaces'],
        ['/project/1/ai/history', 'spaces'],
        ['/project/1/spaces/abc', 'spaces'],
        ['/project/1/feature_flags/920847', 'products'],
        ['/project/1/insights/abc', 'products'],
        ['/project/1/feature_flags', 'products'],
        ['/project/1/data-management/destinations', 'products'],
        ['/project/1/sql', 'products'],
        ['/project/1/views', 'views'],
        ['/project/1/canvases/abc', 'views'],
        ['/project/1/canvases/new', 'views'],
        ['/project/1/notebooks/abc', 'views'],
        ['/project/1/dashboard/12', 'views'],
        ['/project/1/notebooks', 'products'],
        ['/project/1/dashboard', 'products'],
        ['/project/1/persons', 'products'],
        ['/project/1/activity/events', 'products'],
        ['/project/1/airplane', null],
        ['/project/1/homework', null],
    ])('puts %s under %s', (pathname, pane) => {
        expect(railPaneForPath(pathname)).toBe(pane)
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
        ['Notebooks', true],
        ['Dashboards', true],
        ['Session replay', true],
        ['Persons', true],
        ['Activity', true],
        ['SQL editor', true],
        ['Feature flags', false],
        ['Product analytics', false],
        ['Cohorts', false],
    ])('gives %s its own row in the Products list: %s', (label, ownRow) => {
        const rows = getToolSourceItems().filter(isToolItem).map(toolLabel)
        expect(rows.includes(label)).toBe(ownRow)
    })

    it('finds the Insights row with a search for the Product analytics name', () => {
        expect(libraryRowProductLabels('insight')).toContain('Product analytics')
    })

    test.each([
        ['home', '/home'],
        ['spaces', '/spaces/new'],
        ['views', '/views'],
        ['products', '/tools'],
    ] as const)('opens the %s section when its rail item is picked', (pane, pathname) => {
        const logic = todayShellLogic()
        logic.mount()

        router.actions.push('/project/1/airplane')
        logic.actions.pickPane(pane)
        expect(removeProjectIdIfPresent(router.values.location.pathname)).toBe(pathname)
        expect(logic.values.activePane).toBe(pane)
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
})
