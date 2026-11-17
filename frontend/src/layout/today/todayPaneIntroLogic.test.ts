import { initKeaTests } from '~/test/init'

import { todayPaneIntroLogic } from './todayPaneIntroLogic'

describe('todayPaneIntroLogic', () => {
    beforeEach(() => {
        localStorage.clear()
        initKeaTests()
    })

    test('each pane intro is dismissed on its own, and survives a remount', () => {
        const logic = todayPaneIntroLogic()
        logic.mount()
        logic.actions.dismissIntro('analytics')
        logic.actions.dismissIntro('people')
        logic.unmount()

        const remounted = todayPaneIntroLogic()
        remounted.mount()
        expect(remounted.values.dismissedIntros).toEqual({ analytics: true, people: true })
    })
})
