import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { AppContext } from '~/types'

import * as billingResponseWithBillingLimits from '../../mocks/fixtures/_billing_with_billing_limits.json'
import { billingLogic } from './billingLogic'

window.POSTHOG_APP_CONTEXT = { preflight: { cloud: true } } as unknown as AppContext

describe('billingLogic', () => {
    let logic: ReturnType<typeof billingLogic.build>
    beforeEach(() => {
        initKeaTests()
        useMocks({
            get: {
                'api/billing/': {
                    results: billingResponseWithBillingLimits,
                },
                'api/billing/get_invoices': {
                    results: [{}],
                },
            },
        })
    })
    it('over 20k logic respects billing limits', async () => {
        logic = billingLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        await expectLogic(logic).delay(1).toMatchValues({ over20kAnnual: false })
    })
})
