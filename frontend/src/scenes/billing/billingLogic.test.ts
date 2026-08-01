import { expectLogic } from 'kea-test-utils'

import { billingLogic } from 'scenes/billing/billingLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

describe('billingLogic', () => {
    let logic: ReturnType<typeof billingLogic.build>

    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        logic?.unmount()
    })

    it('keeps billing null instead of throwing when the billing service errors', async () => {
        useMocks({ get: { '/api/billing': () => [502, 'Bad Gateway'] } })
        logic = billingLogic()
        logic.mount()

        await expectLogic(logic, () => logic.actions.loadBilling()).toFinishAllListeners()

        expect(logic.values.billing).toBeNull()
    })
})
