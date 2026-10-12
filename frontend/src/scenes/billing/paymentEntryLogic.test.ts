import { waitFor } from '@testing-library/react'
/* oxlint-disable react-hooks/rules-of-hooks -- useMocks is a test helper, not a React hook */
import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

// Imported from the source module rather than the `@posthog/lemon-ui` barrel so that the
// spy below replaces `.error` on the same `lemonToast` singleton that `paymentEntryLogic`
// calls at runtime. `jest.mock('@posthog/lemon-ui', ...)` did not propagate through the
// barrel's re-export chain — spying on the shared object avoids that issue.
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { billingLogic } from 'scenes/billing/billingLogic'
import { paymentEntryLogic } from 'scenes/billing/paymentEntryLogic'
import { organizationLogic } from 'scenes/organizationLogic'
import { userLogic } from 'scenes/userLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { BillingType } from '~/types'

const seedBilling = async (billing: Partial<BillingType> | null): Promise<void> => {
    useMocks({ get: { '/api/billing': () => [200, billing ?? {}] } })
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
        window.history.replaceState({}, '', '/')
    })

    describe('startPaymentEntryFlow — returning customer (customer_id present)', () => {
        beforeEach(async () => {
            await seedBilling({ customer_id: 'cus_test', subscription_level: 'free' })
        })

        const setupActivate = (activate: [number] | [number, unknown]): void => {
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

        it('includes the displayed organization in subscription activation', async () => {
            let body: unknown
            useMocks({
                post: {
                    '/api/billing/activate': async ({ request }) => {
                        body = await request.json()
                        return [200, { must_setup_payment: true }]
                    },
                },
            })
            logic = paymentEntryLogic()
            logic.mount()
            const organizationId = organizationLogic.values.currentOrganization!.id
            await expectLogic(logic, () => logic.actions.startPaymentEntryFlow()).toFinishAllListeners()
            expect(body).toEqual({ organization_id: organizationId, products: 'all_products:' })
            expect(logic.values.paymentOrganizationId).toBe(organizationId)
        })

        it('falls back to a generic toast when activate responds without an error string', async () => {
            setupActivate([200, { success: false }])

            await expectLogic(logic, () => logic.actions.startPaymentEntryFlow()).toFinishAllListeners()

            expect(toastErrorSpy).toHaveBeenCalledWith('Failed to activate subscription')
        })

        it('surfaces a toast when activate throws', async () => {
            // 500 body is unused — api.create rejects on non-2xx before reading JSON.
            setupActivate([500])

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

        it('redirects with upgraded=true when activate succeeds', async () => {
            setupActivate([200, { success: true }])
            const pushSpy = jest.spyOn(router.actions, 'push')

            await expectLogic(logic, () =>
                logic.actions.startPaymentEntryFlow(null, '/project/1/replay/home?foo=bar')
            ).toFinishAllListeners()

            expect(pushSpy).toHaveBeenCalledWith(
                '/project/1/replay/home',
                expect.objectContaining({ foo: 'bar', upgraded: 'true' })
            )
            expect(toastErrorSpy).not.toHaveBeenCalled()
            expect(logic.values.paymentEntryModalOpen).toBe(false)
        })
    })

    describe('startPaymentEntryFlow — new customer (no customer_id)', () => {
        it('authorizes the initiating organization after the current organization changes', async () => {
            await seedBilling({ subscription_level: 'free' })
            const originalOrganization = organizationLogic.values.currentOrganization!
            const bodies: unknown[] = []
            useMocks({
                post: {
                    '/api/billing/activate/authorize': async ({ request }) => {
                        bodies.push(await request.json().catch(() => null))
                        return [200, { clientSecret: 'secret_original' }]
                    },
                },
            })
            logic = paymentEntryLogic()
            logic.mount()
            await expectLogic(logic, () => logic.actions.startPaymentEntryFlow()).toFinishAllListeners()
            organizationLogic.actions.loadCurrentOrganizationSuccess({
                ...originalOrganization,
                id: '00000000-0000-4000-8000-000000000002',
            })
            await expectLogic(logic, () => logic.actions.initiateAuthorization()).toFinishAllListeners()
            expect(bodies).toEqual([{ organization_id: originalOrganization.id }])
        })

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

    describe('startPaymentEntryFlow — billing managed by a partner', () => {
        it('neither activates nor opens the payment modal', async () => {
            await seedBilling({
                subscription_level: 'free',
                billing_managed_by_partner: { partner_name: 'Example Partner' },
            })
            const activate = jest.fn(() => [200, { success: true }] as [number, Record<string, unknown>])
            useMocks({ post: { '/api/billing/activate': activate } })
            logic = paymentEntryLogic()
            logic.mount()

            await expectLogic(logic, () => logic.actions.startPaymentEntryFlow(null, '/foo')).toFinishAllListeners()

            expect(activate).not.toHaveBeenCalled()
            expect(logic.values.paymentEntryModalOpen).toBe(false)
        })
    })

    describe('activation completion after an organization switch', () => {
        it('keeps B selected and shows A in the completion modal after activation succeeds', async () => {
            await seedBilling({ customer_id: 'cus_original', subscription_level: 'free' })
            const original = organizationLogic.values.currentOrganization!
            const selected = { ...original, id: '00000000-0000-4000-8000-000000000002', name: 'Selected organization' }
            let resolveActivation!: (value: [number, unknown]) => void
            const activationResponse = new Promise<[number, unknown]>((resolve) => {
                resolveActivation = resolve
            })
            const activate = jest.fn(() => activationResponse)
            useMocks({ post: { '/api/billing/activate': activate } })
            logic = paymentEntryLogic()
            logic.mount()
            const push = jest.spyOn(router.actions, 'push')
            try {
                logic.actions.startPaymentEntryFlow(null, '/project/1/replay')
                await waitFor(() => expect(activate).toHaveBeenCalledTimes(1))
                organizationLogic.actions.loadCurrentOrganizationSuccess(selected)
                resolveActivation([200, { success: true }])
                await expectLogic(logic).toFinishAllListeners()
                expect(organizationLogic.values.currentOrganization?.id).toBe(selected.id)
                expect(push).not.toHaveBeenCalled()
                expect(logic.values.completedPaymentOrganization).toEqual({ id: original.id, name: original.name })
                expect(logic.values.paymentEntryModalOpen).toBe(true)
            } finally {
                push.mockRestore()
            }
        })
    })

    describe('callback completion while another organization is already selected', () => {
        it.each([true, false])('preserves B when the explicit A name lookup succeeds: %s', async (lookupSucceeds) => {
            await seedBilling({ subscription_level: 'free' })
            const original = {
                ...organizationLogic.values.currentOrganization!,
                id: '00000000-0000-4000-8000-000000000001',
                name: 'Original organization',
            }
            const selected = { ...original, id: '00000000-0000-4000-8000-000000000002', name: 'Selected organization' }
            organizationLogic.actions.loadCurrentOrganizationSuccess(selected)
            const retrieveOriginal = jest.fn(() =>
                lookupSucceeds ? [200, original] : [403, { detail: 'You do not have access to this organization.' }]
            )
            useMocks({
                get: { [`/api/organizations/${original.id}`]: retrieveOriginal },
                post: { '/api/billing/activate/authorize/status': () => [200, { status: 'success' }] },
            })
            window.history.replaceState(
                {},
                '',
                `/billing/authorization_status?organization_id=${original.id}&payment_intent=pi_original`
            )
            logic = paymentEntryLogic()
            logic.mount()
            const push = jest.spyOn(router.actions, 'push')
            try {
                await expectLogic(logic, () => logic.actions.pollAuthorizationStatus()).toFinishAllListeners()
                expect(retrieveOriginal).toHaveBeenCalledTimes(1)
                expect(logic.values.completedPaymentOrganization).toEqual({
                    id: original.id,
                    name: lookupSucceeds ? original.name : 'the original organization',
                })
                expect(logic.values.apiError).toBe(null)
                expect(logic.values.authorizationStatus).toBe('success')
                expect(organizationLogic.values.currentOrganization?.id).toBe(selected.id)
                expect(push).not.toHaveBeenCalled()
            } finally {
                push.mockRestore()
            }
        })
    })

    describe('payment completion for another organization', () => {
        it('keeps the selected organization and requires an explicit switch after successful polling', async () => {
            await seedBilling({ subscription_level: 'free' })
            const original = organizationLogic.values.currentOrganization!
            const selected = { ...original, id: '00000000-0000-4000-8000-000000000002', name: 'Selected organization' }
            useMocks({ post: { '/api/billing/activate/authorize/status': () => [200, { status: 'success' }] } })
            logic = paymentEntryLogic()
            logic.mount()
            logic.actions.beginPaymentFlow(original.id, '/project/1/replay')
            organizationLogic.actions.loadCurrentOrganizationSuccess(selected)
            const push = jest.spyOn(router.actions, 'push')
            const switchOrganization = jest
                .spyOn(userLogic.actions, 'updateCurrentOrganization')
                .mockImplementation(() => undefined)
            try {
                await expectLogic(logic, () =>
                    logic.actions.pollAuthorizationStatus('pi_original')
                ).toFinishAllListeners()
                expect(organizationLogic.values.currentOrganization?.id).toBe(selected.id)
                expect(push).not.toHaveBeenCalled()
                expect(logic.values.completedPaymentOrganization).toEqual({ id: original.id, name: original.name })
                logic.actions.viewCompletedPaymentOrganization()
                expect(switchOrganization).toHaveBeenCalledWith(original.id, '/organization/billing')
            } finally {
                push.mockRestore()
                switchOrganization.mockRestore()
            }
        })
    })

    describe('payment flow organization binding', () => {
        it.each([false, true])(
            'preserves concurrent user state when the selected organization changes: %s',
            async (switchOrganization) => {
                await seedBilling({ subscription_level: 'free' })
                const organization = organizationLogic.values.currentOrganization!
                const user = userLogic.values.user!
                let resolveOrganization!: (value: [number, unknown]) => void
                const response = new Promise<[number, unknown]>((resolve) => {
                    resolveOrganization = resolve
                })
                let requested = false
                useMocks({
                    get: {
                        [`/api/organizations/${organization.id}`]: () => {
                            requested = true
                            return response
                        },
                    },
                })
                logic = paymentEntryLogic()
                logic.mount()
                logic.actions.beginPaymentFlow(organization.id)
                logic.actions.refreshPaymentOrganization(organization.id)
                await waitFor(() => expect(requested).toBe(true))
                const selectedOrganization = switchOrganization
                    ? { ...organization, id: '00000000-0000-4000-8000-000000000002' }
                    : organization
                organizationLogic.actions.loadCurrentOrganizationSuccess(selectedOrganization)
                userLogic.actions.loadUserSuccess({
                    ...user,
                    first_name: 'Updated name',
                    organization: selectedOrganization,
                })
                resolveOrganization([200, { ...organization, customer_id: 'cus_refreshed' }])
                await expectLogic(logic).toFinishAllListeners()
                expect(userLogic.values.user?.first_name).toBe('Updated name')
                expect(userLogic.values.user?.organization?.id).toBe(selectedOrganization.id)
                expect(organizationLogic.values.currentOrganization?.id).toBe(selectedOrganization.id)
                expect(userLogic.values.user?.organization?.customer_id).toBe(
                    switchOrganization ? selectedOrganization.customer_id : 'cus_refreshed'
                )
            }
        )

        it('refreshes original organization billing and entitlements without ambient user or organization reads', async () => {
            await seedBilling({ subscription_level: 'free' })
            const organization = organizationLogic.values.currentOrganization!
            const features = [{ key: 'session_recording', name: 'Session recording', limit: null, note: null }]
            const refreshOrganizations: (string | null)[] = []
            const ambientOrganization = jest.fn(() => [
                200,
                { ...organization, id: '00000000-0000-4000-8000-000000000002' },
            ])
            const ambientUser = jest.fn(() => [
                200,
                {
                    ...userLogic.values.user,
                    organization: { ...organization, id: '00000000-0000-4000-8000-000000000002' },
                },
            ])
            useMocks({
                get: {
                    '/api/billing': ({ request }) => {
                        refreshOrganizations.push(new URL(request.url).searchParams.get('organization_id'))
                        return [200, { subscription_level: 'paid', customer_id: 'cus_original' }]
                    },
                    [`/api/organizations/${organization.id}`]: () => [
                        200,
                        { ...organization, available_product_features: features },
                    ],
                    '/api/organizations/@current': ambientOrganization,
                    '/api/users/@me': ambientUser,
                },
                post: { '/api/billing/activate/authorize/status': () => [200, { status: 'success' }] },
            })
            logic = paymentEntryLogic()
            logic.mount()
            logic.actions.beginPaymentFlow(organization.id, '/project/1/replay')
            await expectLogic(logic, () => logic.actions.pollAuthorizationStatus('pi_original')).toFinishAllListeners()
            expect(refreshOrganizations).toEqual([organization.id])
            expect(ambientOrganization).not.toHaveBeenCalled()
            expect(ambientUser).not.toHaveBeenCalled()
            expect(organizationLogic.values.currentOrganization?.id).toBe(organization.id)
            expect(userLogic.values.user?.organization?.id).toBe(organization.id)
            expect(userLogic.values.user?.organization?.available_product_features).toEqual(features)
            expect(billingLogic.values.billing?.customer_id).toBe('cus_original')
        })

        it('restores the organization and redirect from the Stripe callback', async () => {
            const organizationId = '00000000-0000-4000-8000-000000000002'
            const redirectPath = '/project/2/replay?foo=bar'
            window.history.replaceState(
                {},
                '',
                `/?organization_id=${organizationId}&postRedirectPath=${encodeURIComponent(redirectPath)}`
            )
            logic = paymentEntryLogic()
            logic.mount()
            expect(logic.values.paymentOrganizationId).toBe(organizationId)
            const returnUrl = new URL(logic.values.stripeReturnUrl!)
            expect(returnUrl.pathname).toBe('/billing/authorization_status')
            expect(returnUrl.searchParams.get('organization_id')).toBe(organizationId)
            expect(returnUrl.searchParams.get('postRedirectPath')).toBe(redirectPath)
        })

        it.each(['', '?organization_id=invalid', '?organization_id=@current'])(
            'rejects old or invalid callbacks %s without polling',
            async (query) => {
                const statusRequest = jest.fn(() => [200, { status: 'success' }])
                useMocks({ post: { '/api/billing/activate/authorize/status': statusRequest } })
                window.history.replaceState({}, '', `/${query}`)
                logic = paymentEntryLogic()
                logic.mount()
                await expectLogic(logic, () => logic.actions.pollAuthorizationStatus('pi_test')).toFinishAllListeners()
                expect(statusRequest).not.toHaveBeenCalled()
                expect(logic.values.apiError).toContain('Return to billing and start again')
            }
        )

        it('clears the previous secret and ignores its late response when a new flow starts', async () => {
            let resolveFirst!: (value: [number, { clientSecret: string }]) => void
            const firstResponse = new Promise<[number, { clientSecret: string }]>((resolve) => {
                resolveFirst = resolve
            })
            let calls = 0
            useMocks({
                post: {
                    '/api/billing/activate/authorize': () =>
                        ++calls === 1 ? firstResponse : [200, { clientSecret: 'secret_second' }],
                },
            })
            logic = paymentEntryLogic()
            logic.mount()
            logic.actions.beginPaymentFlow('00000000-0000-4000-8000-000000000001')
            logic.actions.setClientSecret('secret_previous')
            logic.actions.initiateAuthorization()
            await waitFor(() => expect(calls).toBe(1))
            logic.actions.beginPaymentFlow('00000000-0000-4000-8000-000000000002')
            expect(logic.values.clientSecret).toBe(null)
            logic.actions.initiateAuthorization()
            await waitFor(() => expect(logic.values.clientSecret).toBe('secret_second'))
            resolveFirst([200, { clientSecret: 'secret_first' }])
            await expectLogic(logic).toFinishAllListeners()
            expect(logic.values.clientSecret).toBe('secret_second')
        })

        it('keeps the captured redirect through retries while the original organization stays selected', async () => {
            await seedBilling({ subscription_level: 'free' })
            const originalOrganization = organizationLogic.values.currentOrganization!
            const bodies: unknown[] = []
            useMocks({
                post: {
                    '/api/billing/activate/authorize/status': async ({ request }) => {
                        bodies.push(await request.json())
                        return [200, { status: bodies.length === 1 ? 'loading' : 'success' }]
                    },
                },
            })
            logic = paymentEntryLogic()
            logic.mount()
            logic.actions.beginPaymentFlow(originalOrganization.id, '/project/1/replay?foo=bar')
            const pushSpy = jest.spyOn(router.actions, 'push')
            let retry!: () => void
            const originalSetTimeout = global.setTimeout
            const timerSpy = jest.spyOn(global, 'setTimeout').mockImplementation(((
                callback: () => void,
                delay: number,
                ...args: unknown[]
            ) => {
                if (delay === 2000) {
                    retry = callback
                    return 0 as any
                }
                return originalSetTimeout(callback, delay, ...args)
            }) as typeof setTimeout)
            try {
                await expectLogic(logic, () =>
                    logic.actions.pollAuthorizationStatus('pi_original')
                ).toFinishAllListeners()
                logic.actions.setRedirectPath(null)
                retry()
                timerSpy.mockRestore()
                await waitFor(() =>
                    expect(pushSpy).toHaveBeenCalledWith('/project/1/replay', { foo: 'bar', success: true })
                )
                expect(bodies).toEqual(
                    Array(2).fill({ organization_id: originalOrganization.id, payment_intent_id: 'pi_original' })
                )
            } finally {
                timerSpy.mockRestore()
                pushSpy.mockRestore()
            }
        })
    })
})
