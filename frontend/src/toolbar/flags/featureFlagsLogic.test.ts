import { expectLogic } from 'kea-test-utils'
import { initKeaTestLogic } from '~/test/init'
import { featureFlagsLogic } from '~/toolbar/flags/featureFlagsLogic'
import { toolbarLogic } from '~/toolbar/toolbarLogic'

describe('feature flags logic', () => {
    let logic: ReturnType<typeof featureFlagsLogic.build>

    initKeaTestLogic()

    beforeEach(() => {
        toolbarLogic({ apiURL: 'http://localhost' }).mount()
        logic = featureFlagsLogic()
        logic.mount()
    })

    it('has expected defaults', () => {
        expectLogic(logic).toMatchValues({
            userFlags: [],
        })
    })
})
