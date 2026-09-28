import { router } from 'kea-router'

import { initKeaTests } from '~/test/init'

import { railPaneForPath, todayShellLogic } from './todayShellLogic'

describe('todayShellLogic', () => {
    beforeEach(() => {
        initKeaTests()
    })

    test.each([
        ['/project/1/home', 'home'],
        ['/project/1/ai', 'spaces'],
        ['/project/1/ai/history', 'spaces'],
        ['/project/1/insights/abc', null],
        ['/project/1/airplane', null],
    ])('puts %s under %s', (path, pane) => {
        expect(railPaneForPath(path)).toBe(pane)
    })

    it('keeps a picked pane open until the route moves to a page that owns a pane', () => {
        const logic = todayShellLogic()
        logic.mount()

        logic.actions.pickPane('library')
        router.actions.push('/project/1/insights/abc')
        expect(logic.values.activePane).toBe('library')

        router.actions.push('/project/1/ai')
        expect(logic.values.activePane).toBe('spaces')
    })
})
