import { router } from 'kea-router'

import { billingLogic } from 'scenes/billing/billingLogic'

import { ProductKey } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { BillingType } from '~/types'

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

        it('falls back to the parent product when the add-on has no anchor', () => {
            billingLogic.mount()
            billingLogic.actions.loadBillingSuccess({
                products: [{ type: 'platform_and_support', addons: [{ type: 'enterprise' }] }],
            } as BillingType)
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
