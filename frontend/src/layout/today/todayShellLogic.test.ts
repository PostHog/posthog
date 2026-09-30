import { router } from 'kea-router'

import { initKeaTests } from '~/test/init'

import {
    TODAY_RAIL_WIDTH,
    TODAY_SIDEBAR_MAX_WIDTH,
    landingPaneForPath,
    railPaneForPath,
    todayShellLogic,
} from './todayShellLogic'

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
        ['/project/1/insights/abc', null],
        ['/project/1/airplane', null],
        ['/project/1/homework', null],
    ])('puts %s under %s', (pathname, pane) => {
        expect(railPaneForPath(pathname)).toBe(pane)
    })

    test.each([
        ['/project/1/feature_flags/42', 'library'],
        ['/project/1/insights/abc', 'library'],
        ['/project/1/dashboard/7', 'library'],
        ['/project/1/visual_review/runs/abc', 'tools'],
        ['/project/1/visual_review', 'tools'],
        ['/project/1/visual_reviewer', null],
        ['/project/1/ai', 'spaces'],
    ])('lands on %s with %s open', (pathname, pane) => {
        expect(landingPaneForPath(pathname, ['/visual_review?tab=runs'])).toBe(pane)
    })

    it('opens the pane of the first page only, and keeps it when later pages belong to another', () => {
        router.actions.push('/project/1/feature_flags/42')
        const logic = todayShellLogic()
        logic.mount()
        expect(logic.values.activePane).toBe('library')

        router.actions.push('/project/1/sql')
        expect(logic.values.activePane).toBe('library')
    })

    it('keeps the last pane open on pages that belong to no pane', () => {
        const logic = todayShellLogic()
        logic.mount()

        logic.actions.pickPane('tools')
        router.actions.push('/project/1/insights/abc')
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
