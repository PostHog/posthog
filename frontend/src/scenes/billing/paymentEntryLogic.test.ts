/* oxlint-disable react-hooks/rules-of-hooks -- useMocks is a test helper, not a React hook */
import { expectLogic } from 'kea-test-utils'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { billingLogic } from 'scenes/billing/billingLogic'
import { paymentEntryLogic } from 'scenes/billing/paymentEntryLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { BillingType } from '~/types'

const seedBilling = async (billing: Partial<BillingType> | null): Promise<void> => {
    useMocks({
        get: {
            '/api/billing/': () => [200, billing ?? {}],
            '/api/billing': () => [200, billing ?? {}],
        },
    })
    billingLogic.mount()
    await expectLogic(billingLogic, () => billingLogic.actions.loadBilling()).toFinishAllListeners()
}

describe('paymentEntryLogic', () => {
    let logic: ReturnType<typeof paymentEntryLogic.build>
    let toastErrorSpy: jest.SpyInstance

    beforeEach(() => {
        initKeaTests()
        toastErrorSpy = jest.spyOn(lemonToast, 'error').mockImplementation(() => ({ id: 'x' }) as any)
    })

    afterEach(() => {
        logic?.unmount()
        toastErrorSpy.mockRestore()
    })

    describe('startPaymentEntryFlow — returning customer (customer_id present)', () => {
        beforeEach(async () => {
            await seedBilling({ customer_id: 'cus_test', subscription_level: 'free' })
        })

        const setupActivate = (activate: [number, unknown]): void => {
            useMocks({ post: { '/api/billing/activate': () => activate } })
            logic = paymentEntryLogic()
            logic.mount()
        }

        it('surfaces a toast when activate responds with an error payload', async () => {
            setupActivate([200, { success: false, error: 'test failure' }])

            await expectLogic(logic, () => logic.actions.startPaymentEntryFlow()).toFinishAllListeners()

            expect(toastErrorSpy).toHaveBeenCalledWith('test failure')
            expect(logic.values.paymentEntryModalOpen).toBe(false)
            expect(logic.values.apiError).toBe(null)
        })

        it('falls back to a generic toast when activate responds without an error string', async () => {
            setupActivate([200, { success: false }])

            await expectLogic(logic, () => logic.actions.startPaymentEntryFlow()).toFinishAllListeners()

            expect(toastErrorSpy).toHaveBeenCalledWith('Failed to activate subscription')
        })

        it('surfaces a toast when activate throws', async () => {
            setupActivate([500, { detail: 'boom' }])

            await expectLogic(logic, () => logic.actions.startPaymentEntryFlow()).toFinishAllListeners()

            expect(toastErrorSpy).toHaveBeenCalledWith('Failed to activate subscription. Please try again.')
            expect(logic.values.paymentEntryModalOpen).toBe(false)
            expect(logic.values.apiError).toBe(null)
        })

        it('opens the payment entry modal when activate signals must_setup_payment', async () => {
            setupActivate([200, { must_setup_payment: true }])

            await expectLogic(logic, () =>
                logic.actions.startPaymentEntryFlow(null, '/replay/home')
            ).toFinishAllListeners()

            expect(logic.values.paymentEntryModalOpen).toBe(true)
            expect(logic.values.redirectPath).toBe('/replay/home')
            expect(toastErrorSpy).not.toHaveBeenCalled()
        })
    })

    describe('startPaymentEntryFlow — new customer (no customer_id)', () => {
        it('opens the payment entry modal without calling activate', async () => {
            await seedBilling({ subscription_level: 'free' })
            const activate = jest.fn(() => [200, { success: true }] as [number, Record<string, unknown>])
            useMocks({ post: { '/api/billing/activate': activate } })
            logic = paymentEntryLogic()
            logic.mount()

            await expectLogic(logic, () => logic.actions.startPaymentEntryFlow(null, '/foo')).toFinishAllListeners()

            expect(activate).not.toHaveBeenCalled()
            expect(logic.values.paymentEntryModalOpen).toBe(true)
            expect(logic.values.redirectPath).toBe('/foo')
            expect(toastErrorSpy).not.toHaveBeenCalled()
        })
    })
})
