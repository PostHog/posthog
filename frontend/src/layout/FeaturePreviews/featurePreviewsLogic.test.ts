import { expectLogic } from 'kea-test-utils'
import { MOCK_DEFAULT_USER } from 'lib/api.mock'
import { userLogic } from 'scenes/userLogic'

import { initKeaTests } from '~/test/init'

import { featurePreviewsLogic } from './featurePreviewsLogic'

describe('featurePreviewsLogic', () => {
    let logic: ReturnType<typeof featurePreviewsLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = featurePreviewsLogic()
        logic.mount()
        userLogic.actions.loadUserSuccess(MOCK_DEFAULT_USER)
    })

    test('submitting feedback', async () => {
        logic.actions.beginEarlyAccessFeatureFeedback('test')
        const promise = logic.asyncActions.submitEarlyAccessFeatureFeedback('test')
        await expectLogic(logic)
            .toMatchValues({ activeFeedbackFlagKeyLoading: true })
            .toDispatchActions(['submitEarlyAccessFeatureFeedback'])
            .toNotHaveDispatchedActions(['submitEarlyAccessFeatureFeedbackSuccess'])
        await promise
        await expectLogic(logic)
            .toMatchValues({ activeFeedbackFlagKeyLoading: false })
            .toDispatchActions(['submitEarlyAccessFeatureFeedbackSuccess'])
    })
})
