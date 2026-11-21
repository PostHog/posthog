import { initKeaTests } from '~/test/init'

import { SCENE_TABS_RELEASE_DELAY_MS, todaySceneTabsLogic } from './todaySceneTabsLogic'

describe('todaySceneTabsLogic', () => {
    beforeEach(() => {
        jest.useFakeTimers()
        initKeaTests()
    })

    afterEach(() => {
        jest.useRealTimers()
    })

    it('keeps the tabs mounted briefly after the last one goes, then releases', () => {
        const logic = todaySceneTabsLogic()
        logic.mount()
        logic.actions.addSceneTabs()
        logic.actions.removeSceneTabs()

        jest.advanceTimersByTime(SCENE_TABS_RELEASE_DELAY_MS - 1)
        expect(logic.values.sceneTabsMounted).toBe(true)
        jest.advanceTimersByTime(1)
        expect(logic.values.sceneTabsMounted).toBe(false)
    })

    it('stays mounted when new tabs arrive within the hold', () => {
        const logic = todaySceneTabsLogic()
        logic.mount()
        logic.actions.addSceneTabs()
        logic.actions.removeSceneTabs()
        jest.advanceTimersByTime(SCENE_TABS_RELEASE_DELAY_MS - 1)
        logic.actions.addSceneTabs()

        jest.advanceTimersByTime(SCENE_TABS_RELEASE_DELAY_MS * 2)
        expect(logic.values.sceneTabsMounted).toBe(true)
        expect(logic.values.mountedCount).toBe(1)
    })

    it('clamps the count at zero', () => {
        const logic = todaySceneTabsLogic()
        logic.mount()
        logic.actions.removeSceneTabs()
        expect(logic.values.mountedCount).toBe(0)
        jest.advanceTimersByTime(SCENE_TABS_RELEASE_DELAY_MS)
        expect(logic.values.sceneTabsMounted).toBe(false)
    })
})
