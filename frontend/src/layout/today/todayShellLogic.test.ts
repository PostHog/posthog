import { router } from 'kea-router'

import { initKeaTests } from '~/test/init'

import { TODAY_RAIL_WIDTH, TODAY_SIDEBAR_MAX_WIDTH, railPaneForPath, todayShellLogic } from './todayShellLogic'
import { toolHrefForPath } from './todayToolsLogic'

describe('todayShellLogic', () => {
    beforeEach(() => {
        initKeaTests()
    })

    test.each([
        ['/project/1/home', 'home'],
        ['/project/1/home/reports/abc', 'home'],
        ['/project/1/library', 'library'],
        ['/project/1/library/feature_flag', 'library'],
        ['/project/1/ai', 'spaces'],
        ['/project/1/ai/history', 'spaces'],
        ['/project/1/spaces/abc', 'spaces'],
        ['/project/1/feature_flags/920847', 'library'],
        ['/project/1/insights/abc', 'library'],
        ['/project/1/feature_flags', 'library'],
        ['/project/1/data-management/destinations', 'tools'],
        ['/project/1/sql', 'tools'],
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

    it('keeps the last pane open on pages that belong to no pane', () => {
        const logic = todayShellLogic()
        logic.mount()

        logic.actions.pickPane('tools')
        router.actions.push('/project/1/airplane')
        expect(logic.values.activePane).toBe('tools')

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
})
