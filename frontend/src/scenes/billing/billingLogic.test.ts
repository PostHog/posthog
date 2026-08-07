import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { billingLogic } from 'scenes/billing/billingLogic'

import { billingJson } from '~/mocks/fixtures/_billing'
import { useMocks } from '~/mocks/jest'
import { ProductKey } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

describe('billingLogic', () => {
    beforeEach(() => {
        initKeaTests()
    })

    describe('scrollToProduct', () => {
        const addAnchor = (dataAttr: string): jest.Mock => {
            const el = document.createElement('div')
            el.setAttribute('data-attr', dataAttr)
            const scrollIntoView = jest.fn()
            el.scrollIntoView = scrollIntoView
            document.body.appendChild(el)
            return scrollIntoView
        }

        afterEach(() => {
            document.body.innerHTML = ''
        })

        it('scrolls to the add-on anchor when it exists', () => {
            billingLogic.mount()
            const scrollIntoView = addAnchor('billing-product-addon-enterprise')

            billingLogic.actions.scrollToProduct('enterprise')

            expect(scrollIntoView).toHaveBeenCalledTimes(1)
        })

        it('falls back to the parent product when the add-on has no anchor', async () => {
            // billingJson's platform_and_support product carries the enterprise add-on, which is
            // rendered without its own anchor — so the scroll must fall back to the parent product.
            useMocks({ get: { '/api/billing': () => [200, billingJson] } })
            billingLogic.mount()
            await expectLogic(billingLogic, () => billingLogic.actions.loadBilling()).toFinishAllListeners()
            const parentScrollIntoView = addAnchor('billing-product-platform_and_support')

            billingLogic.actions.scrollToProduct('enterprise')

            expect(parentScrollIntoView).toHaveBeenCalledTimes(1)
        })
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
})
