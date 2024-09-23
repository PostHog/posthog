import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { AppContext } from '~/types'

import * as billingResponseWithBillingLimits from '../../mocks/fixtures/_billing_with_billing_limits.json'

window.POSTHOG_APP_CONTEXT = { preflight: { cloud: true } } as unknown as AppContext

describe('billingLogic', () => {
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
})
