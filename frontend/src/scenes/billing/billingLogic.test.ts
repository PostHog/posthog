import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
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

    it('shows the billing service reason when a limit update is rejected', async () => {
        const toastErrorSpy = jest.spyOn(lemonToast, 'error').mockImplementation(() => ({ id: 'x' }) as any)
        useMocks({
            patch: {
                '/api/billing': () => [400, { detail: 'Cannot set a limit below your current usage' }],
            },
        })
        billingLogic.mount()

        await expectLogic(billingLogic, () => {
            billingLogic.actions.updateBillingLimits({ product_analytics: 0 })
        }).toFinishAllListeners()

        expect(toastErrorSpy).toHaveBeenCalledWith('Cannot set a limit below your current usage')
        toastErrorSpy.mockRestore()
    })
})
