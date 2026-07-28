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
        logic.actions.registerScenePanelElement(element)
        expect(logic.values.scenePanelElement).toBe(element)

        logic.actions.registerScenePanelElement(null)

        // `lastResult` is a reselect 5 internal, not a public API — if a future
        // kea/reselect upgrade renames it, this cast fails mechanically (TypeError),
        // it isn't a behavioural regression in the fix itself.
        const lastResult = (logic.selectors.scenePanelElement as unknown as { lastResult: () => HTMLElement | null })
            .lastResult
        expect(lastResult()).toBe(null)
    })
})
