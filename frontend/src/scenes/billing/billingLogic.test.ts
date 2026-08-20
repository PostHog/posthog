import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { billingLogic } from 'scenes/billing/billingLogic'

import { useMocks } from '~/mocks/jest'
import { ProductKey } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

describe('billingLogic', () => {
    beforeEach(() => {
        initKeaTests()
    })

    it.each(['/organization/billing', '/organization/billing/overview'])(
        'restores product deep-link scrolling from %s after mount',
        (pathname) => {
            billingLogic.mount()
            router.actions.push(pathname, { products: ProductKey.REPLAY_VISION })

            expect(billingLogic.values.scrollToProductKey).toBe(ProductKey.REPLAY_VISION)
        }
    )

    it.each(['/organization/billing', '/organization/billing/overview'])(
        'restores product deep-link scrolling from %s on initial mount',
        (pathname) => {
            router.actions.push(pathname, { products: ProductKey.REPLAY_VISION })
            billingLogic.mount()

            expect(billingLogic.values.scrollToProductKey).toBe(ProductKey.REPLAY_VISION)
        }
    )

    it.each(['/organization/billing/usage', '/organization/billing/spend'])(
        'does not restore product deep-link scrolling from %s after mount',
        (pathname) => {
            billingLogic.mount()
            router.actions.push(pathname, { products: ProductKey.REPLAY_VISION })

            expect(billingLogic.values.scrollToProductKey).toBe(null)
        }
    )

    it.each(['/organization/billing/usage', '/organization/billing/spend'])(
        'does not restore product deep-link scrolling from %s on initial mount',
        (pathname) => {
            router.actions.push(pathname, { products: ProductKey.REPLAY_VISION })
            billingLogic.mount()

            expect(billingLogic.values.scrollToProductKey).toBe(null)
        }
    )

    // The endpoint returns 404 by design on a non-v2 license or legacy Cloud billing. That must
    // resolve to empty billing, not a loader failure — a failure reaches error tracking.
    it('resolves billing to null when the endpoint returns a by-design 404', async () => {
        useMocks({ get: { '/api/billing': () => [404, { detail: 'Billing is not supported for this license type' }] } })
        billingLogic.mount()

        await expectLogic(billingLogic, () => billingLogic.actions.loadBilling())
            .toDispatchActions(['loadBillingSuccess'])
            .toNotHaveDispatchedActions(['loadBillingFailure'])
        expect(billingLogic.values.billing).toBe(null)
    })

    it('rethrows a non-404 billing error so error tracking still sees it', async () => {
        useMocks({ get: { '/api/billing': () => [500, { detail: 'boom' }] } })
        billingLogic.mount()

        await expectLogic(billingLogic, () => billingLogic.actions.loadBilling()).toDispatchActions([
            'loadBillingFailure',
        ])
    })
})
