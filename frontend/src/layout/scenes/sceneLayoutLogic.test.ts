import { initKeaTests } from '~/test/init'

import { sceneLayoutLogic } from './sceneLayoutLogic'

describe('sceneLayoutLogic', () => {
    let logic: ReturnType<typeof sceneLayoutLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = sceneLayoutLogic()
        logic.mount()
    })

    it('releases the previous panel element from the memoized selector cache', () => {
        // Regression guard for detached-DOM retention: with no ScenePanel
        // subscribed, the reselect cache is only refreshed by the
        // registerScenePanelElement listener. If that listener is removed, the
        // stale cached element pins the departed scene's whole fiber/DOM tree.
        const element = document.createElement('div')
        logic.actions.registerScenePanelElement('inline', element)
        expect(logic.values.scenePanelElement).toBe(element)

        const readPanelElement = jest.spyOn(logic.selectors, 'scenePanelElement')
        logic.actions.registerScenePanelElement('inline', null)

        expect(readPanelElement).toHaveBeenCalled()
        expect(logic.values.scenePanelElement).toBe(null)
    })

    it('counts scene panels so one closing does not take the host down', () => {
        logic.actions.registerScenePanel()
        logic.actions.registerScenePanel()
        logic.actions.unregisterScenePanel()
        expect(logic.values.scenePanelIsPresent).toBe(true)

        logic.actions.unregisterScenePanel()
        expect(logic.values.scenePanelIsPresent).toBe(false)
    })
})
