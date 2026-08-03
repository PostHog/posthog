/* oxlint-disable react-hooks/rules-of-hooks -- useMocks is a test helper, not a React hook */
import { expectLogic } from 'kea-test-utils'

import { preflightLogic } from 'lib/logic/preflightLogic'
import { billingLogic } from 'scenes/billing/billingLogic'

import { billingJson } from '~/mocks/fixtures/_billing'
import preflightJson from '~/mocks/fixtures/_preflight.json'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { BillingType } from '~/types'

describe('billingLogic', () => {
    afterEach(() => {
        billingLogic.unmount()
    })

    const mountWithUsage = async (percentage_usage: number): Promise<ReturnType<typeof billingLogic.build>> => {
        const products = billingJson.products.map((product) =>
            product.type === 'product_analytics' ? { ...product, percentage_usage } : product
        )
        useMocks({
            get: {
                '/api/billing': () => [200, { ...billingJson, products } satisfies BillingType],
                '/_preflight': () => [200, { ...preflightJson, cloud: true }],
            },
        })
        initKeaTests()
        const preflight = preflightLogic()
        preflight.mount()
        await expectLogic(preflight).toFinishAllListeners()

        const logic = billingLogic()
        logic.mount()
        await expectLogic(logic, () => logic.actions.loadBilling()).toFinishAllListeners()
        return logic
    }

    // A product sitting at exactly 100% usage must be treated as "exceeded", not "approaching" —
    // otherwise the banner tells the user they'll "soon" hit a limit they've already hit.
    it.each([
        ['just under the limit', 0.99, 'approaching'],
        ['exactly at the limit', 1, 'exceeded'],
        ['over the limit', 1.5, 'exceeded'],
    ] as const)('buckets a product %s (%s%%) as %s', async (_name, percentage_usage, bucket) => {
        const logic = await mountWithUsage(percentage_usage)

        expect(logic.values.billingAlert?.title).toContain(bucket === 'exceeded' ? 'exceeded' : 'will soon hit')
    })
})
