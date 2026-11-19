import { MOCK_DEFAULT_USER } from 'lib/api.mock'

import { userLogic } from 'scenes/userLogic'

import { initKeaTests } from '~/test/init'

import { todayPaneIntroLogic } from './todayPaneIntroLogic'
import { todayTourLogic } from './todayTourLogic'

describe('todayPaneIntroLogic', () => {
    let logic: ReturnType<typeof todayPaneIntroLogic.build>

    beforeEach(() => {
        initKeaTests()
        userLogic.mount()
        userLogic.actions.loadUserSuccess({
            ...MOCK_DEFAULT_USER,
            has_seen_product_intro_for: { today_pane_intro_monitor: true },
        })
        logic = todayPaneIntroLogic()
        logic.mount()
    })

    test('each pane intro is dismissed on its own', () => {
        logic.actions.dismissIntro('analytics')

        expect(logic.values.isIntroShown('analytics')).toBe(false)
        expect(logic.values.isIntroShown('people')).toBe(true)
    })

    test('an intro dismissed on the user stays hidden, and the tour shows it again', () => {
        expect(logic.values.isIntroShown('monitor')).toBe(false)

        todayTourLogic.actions.startTour({ x: 0, y: 0 })

        expect(logic.values.isIntroShown('monitor')).toBe(true)
    })
})
