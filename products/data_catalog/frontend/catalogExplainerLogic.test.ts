import { MOCK_DEFAULT_USER } from 'lib/api.mock'

import { userLogic } from 'scenes/userLogic'

import { initKeaTests } from '~/test/init'
import { expectLogic } from '~/test/keaTestUtils'

import { EXPLAINER_DISMISSED_KEY, catalogExplainerLogic } from './catalogExplainerLogic'

describe('catalogExplainerLogic', () => {
    let logic: ReturnType<typeof catalogExplainerLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = catalogExplainerLogic()
        logic.mount()
    })

    it('hides the explainer at once on dismiss and stores the dismissal on the user', async () => {
        expect(logic.values.explainerDismissed).toBe(false)

        await expectLogic(logic, () => logic.actions.dismissExplainer())
            .toDispatchActions([userLogic.actionCreators.updateHasSeenProductIntroFor(EXPLAINER_DISMISSED_KEY)])
            .toMatchValues({ explainerDismissed: true })
    })

    it('stays hidden for a user who dismissed it before', () => {
        userLogic.actions.loadUserSuccess({
            ...MOCK_DEFAULT_USER,
            has_seen_product_intro_for: { [EXPLAINER_DISMISSED_KEY]: true },
        })

        expect(logic.values.explainerDismissed).toBe(true)
    })
})
