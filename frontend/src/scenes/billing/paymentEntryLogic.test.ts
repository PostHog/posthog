import type { Stripe, StripeElements } from '@stripe/stripe-js'
import { waitFor } from '@testing-library/react'
/* oxlint-disable react-hooks/rules-of-hooks -- useMocks is a test helper, not a React hook */
import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

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
import { AvailableFeature, BillingType } from '~/types'

const OTHER_ORGANIZATION_ID = '00000000-0000-4000-8000-000000000002'

const seedBilling = async (billing: Partial<BillingType> | null): Promise<void> => {
    useMocks({ get: { '/api/billing': () => [200, billing ?? {}] } })
    billingLogic.mount()
    await expectLogic(billingLogic, () => billingLogic.actions.loadBilling()).toFinishAllListeners()
}

const deferred = <T>(): { promise: Promise<T>; resolve: (value: T) => void; reject: (error: unknown) => void } => {
    let resolve!: (value: T) => void
    let reject!: (error: unknown) => void
    const promise = new Promise<T>((res, rej) => {
        resolve = res
        reject = rej
    })
    return { promise, resolve, reject }
}

const fakeStripe = (confirmPayment: () => Promise<unknown>): Stripe => ({ confirmPayment }) as unknown as Stripe
const fakeElements = {} as StripeElements

const setDocumentHidden = (hidden: boolean): void => {
    Object.defineProperty(document, 'hidden', { configurable: true, get: () => hidden })
    document.dispatchEvent(new Event('visibilitychange'))
}

// Holds the 2 second status retries so a test can fire them; clearing one drops it like a real timer.
const holdStatusRetries = (): { fire: () => Promise<void>; restore: () => void } => {
    const retries = new Map<number, () => void>()
    let nextId = 1_000_000
    const { setTimeout: realSetTimeout, clearTimeout: realClearTimeout } = global
    const setSpy = jest.spyOn(global, 'setTimeout').mockImplementation(((
        callback: () => void,
        delay?: number,
        ...args: unknown[]
    ) => {
        if (delay !== 2000) {
            return realSetTimeout(callback, delay, ...args)
        }
        retries.set(++nextId, callback)
        return nextId
    }) as typeof setTimeout)
    const clearSpy = jest.spyOn(global, 'clearTimeout').mockImplementation(((id: number) => {
        if (!retries.delete(id)) {
            realClearTimeout(id)
        }
    }) as typeof clearTimeout)
    return {
        fire: async () => {
            const callbacks = [...retries.values()]
            retries.clear()
            callbacks.forEach((callback) => callback())
            await new Promise((resolve) => realSetTimeout(resolve, 0))
        },
        restore: () => {
            setSpy.mockRestore()
            clearSpy.mockRestore()
        },
    }
}

describe('paymentEntryLogic', () => {
    let logic: ReturnType<typeof paymentEntryLogic.build>
    let toastErrorSpy: jest.SpyInstance
    let toastInfoSpy: jest.SpyInstance

    beforeEach(() => {
        initKeaTests()
        toastErrorSpy = jest.spyOn(lemonToast, 'error').mockImplementation(() => ({ id: 'x' }) as any)
        toastInfoSpy = jest.spyOn(lemonToast, 'info').mockImplementation(() => ({ id: 'x' }) as any)
    })

    afterEach(() => {
        logic?.unmount()
        toastErrorSpy.mockRestore()
        toastInfoSpy.mockRestore()
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

        it('lets the next start activate again after an activation error', async () => {
            const activate = jest.fn(() => [200, { success: false, error: 'test failure' }])
            useMocks({ post: { '/api/billing/activate': activate } })
            logic = paymentEntryLogic()
            logic.mount()

            await expectLogic(logic, () => logic.actions.startPaymentEntryFlow()).toFinishAllListeners()
            await expectLogic(logic, () => logic.actions.startPaymentEntryFlow()).toFinishAllListeners()

            expect(activate).toHaveBeenCalledTimes(2)
            expect(toastInfoSpy).not.toHaveBeenCalled()
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
                const response = deferred<[number, unknown]>()
                let requested = false
                useMocks({
                    get: {
                        [`/api/organizations/${organization.id}`]: () => {
                            requested = true
                            return response.promise
                        },
                    },
                })
                logic = paymentEntryLogic()
                logic.mount()
                logic.actions.beginPaymentFlow(organization.id)
                logic.actions.completePaymentFlow(null, { success: true })
                await waitFor(() => expect(requested).toBe(true))
                const selectedOrganization = switchOrganization
                    ? { ...organization, id: OTHER_ORGANIZATION_ID }
                    : organization
                organizationLogic.actions.loadCurrentOrganizationSuccess(selectedOrganization)
                userLogic.actions.loadUserSuccess({
                    ...user,
                    first_name: 'Updated name',
                    organization: selectedOrganization,
                })
                response.resolve([200, { ...organization, customer_id: 'cus_refreshed' }])
                await expectLogic(logic).toFinishAllListeners()
                expect(userLogic.values.user?.first_name).toBe('Updated name')
                expect(userLogic.values.user?.organization?.id).toBe(selectedOrganization.id)
                expect(organizationLogic.values.currentOrganization?.id).toBe(selectedOrganization.id)
                expect(userLogic.values.user?.organization?.customer_id).toBe(
                    switchOrganization ? selectedOrganization.customer_id : 'cus_refreshed'
                )
            }
        )

        it('leaves billing alone when another organization is selected while the paid billing loads', async () => {
            await seedBilling({ subscription_level: 'free' })
            const original = organizationLogic.values.currentOrganization!
            const billingBefore = billingLogic.values.billing
            const billingResponse = deferred<[number, unknown]>()
            let requested = false
            useMocks({
                get: {
                    '/api/billing': () => {
                        requested = true
                        return billingResponse.promise
                    },
                },
            })
            logic = paymentEntryLogic()
            logic.mount()
            logic.actions.beginPaymentFlow(original.id)
            logic.actions.completePaymentFlow(null, { success: true })
            await waitFor(() => expect(requested).toBe(true))
            organizationLogic.actions.loadCurrentOrganizationSuccess({ ...original, id: OTHER_ORGANIZATION_ID })
            billingResponse.resolve([200, { subscription_level: 'paid', customer_id: 'cus_paid' }])
            await expectLogic(logic).toFinishAllListeners()
            expect(billingLogic.values.billing).toBe(billingBefore)
            expect(logic.values.completedPaymentOrganization).toEqual({ id: original.id, name: original.name })
        })

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

        it('applies the features the billing read saves after an add-on purchase', async () => {
            await seedBilling({ customer_id: 'cus_paid', subscription_level: 'paid' })
            const organization = organizationLogic.values.currentOrganization!
            const features = [
                { key: AvailableFeature.GROUP_ANALYTICS, name: 'Group analytics', limit: null, note: null },
            ]
            let billingSaved = false
            useMocks({
                get: {
                    '/api/billing': async () => {
                        await new Promise((resolve) => setTimeout(resolve, 50))
                        billingSaved = true
                        return [200, { customer_id: 'cus_paid', subscription_level: 'paid' }]
                    },
                    [`/api/organizations/${organization.id}`]: () => [
                        200,
                        {
                            ...organization,
                            available_product_features: billingSaved
                                ? features
                                : organization.available_product_features,
                        },
                    ],
                },
                post: { '/api/billing/activate': () => [200, { success: true }] },
            })
            logic = paymentEntryLogic()
            logic.mount()
            expect(userLogic.values.hasAvailableFeature(AvailableFeature.GROUP_ANALYTICS)).toBe(false)
            await expectLogic(logic, () => logic.actions.upgradeProducts('scale:scale', null)).toFinishAllListeners()
            expect(userLogic.values.hasAvailableFeature(AvailableFeature.GROUP_ANALYTICS)).toBe(true)
        })

        it.each([
            ['/organization/billing', { upgraded: 'true' }],
            ['/onboarding/product_analytics', { success: 'true' }],
        ])('keeps the paid organization when a payment completes on %s', async (pathname, params) => {
            await seedBilling({ customer_id: 'cus_paid', subscription_level: 'paid' })
            const organization = organizationLogic.values.currentOrganization!
            const other = { ...organization, id: OTHER_ORGANIZATION_ID, name: 'Other organization' }
            const ambientCredits = jest.fn(() => [200, { eligible: true, email: 'other@example.com' }])
            const ambientUser = jest.fn(() => [200, { ...userLogic.values.user, organization: other }])
            const ambientOrganization = jest.fn(() => [200, other])
            useMocks({
                get: {
                    '/api/billing': () => [
                        200,
                        { customer_id: 'cus_paid', subscription_level: 'paid', has_active_subscription: true },
                    ],
                    [`/api/organizations/${organization.id}`]: () => [200, organization],
                    '/api/billing/credits/overview': ambientCredits,
                    '/api/users/@me': ambientUser,
                    '/api/organizations/@current': ambientOrganization,
                },
                post: { '/api/billing/activate': () => [200, { success: true }] },
            })
            router.actions.push(pathname, params)
            logic = paymentEntryLogic()
            logic.mount()
            jest.useFakeTimers()
            try {
                const upgrade = logic.asyncActions.upgradeProducts('scale:scale', null)
                await jest.advanceTimersByTimeAsync(2000)
                await upgrade
                await expectLogic(billingLogic).toFinishAllListeners()
                await expectLogic(userLogic).toFinishAllListeners()
                await expectLogic(organizationLogic).toFinishAllListeners()
            } finally {
                jest.useRealTimers()
            }
            expect(ambientCredits).not.toHaveBeenCalled()
            expect(ambientUser).not.toHaveBeenCalled()
            expect(ambientOrganization).not.toHaveBeenCalled()
            expect(billingLogic.values.billing?.has_active_subscription).toBe(true)
            expect(organizationLogic.values.currentOrganization?.id).toBe(organization.id)
            expect(userLogic.values.user?.organization?.id).toBe(organization.id)
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

    describe('closing the modal after the card is submitted', () => {
        let pushSpy: jest.SpyInstance
        const features = [{ key: 'session_recording', name: 'Session recording', limit: null, note: null }]

        const mockPaidOrganization = (statuses: string[]): jest.Mock => {
            const organization = organizationLogic.values.currentOrganization!
            const statusRequest = jest.fn(() => [200, { status: statuses.shift() ?? 'success' }])
            useMocks({
                get: {
                    '/api/billing': () => [200, { subscription_level: 'paid', customer_id: 'cus_paid' }],
                    [`/api/organizations/${organization.id}`]: () => [
                        200,
                        { ...organization, available_product_features: features },
                    ],
                },
                post: { '/api/billing/activate/authorize/status': statusRequest },
            })
            return statusRequest
        }

        const expectPaidOrganizationApplied = (): void => {
            expect(billingLogic.values.billing?.customer_id).toBe('cus_paid')
            expect(organizationLogic.values.currentOrganization?.available_product_features).toEqual(features)
            expect(userLogic.values.user?.organization?.available_product_features).toEqual(features)
            expect(pushSpy).toHaveBeenCalledWith('/project/1/replay', { success: true })
        }

        const submitCard = (): void =>
            logic.actions.confirmPayment(
                fakeStripe(async () => ({ paymentIntent: { id: 'pi_submitted' } })),
                fakeElements
            )

        const startAgainAndExpectRefusal = (): void => {
            const flow = logic.values.paymentFlow
            logic.actions.startPaymentEntryFlow(null, '/project/1/replay')
            expect(toastInfoSpy).toHaveBeenCalledWith("We're still confirming your last payment.")
            expect(logic.values.paymentEntryModalOpen).toBe(false)
            expect(logic.values.paymentFlow).toBe(flow)
        }

        beforeEach(async () => {
            await seedBilling({ subscription_level: 'free' })
            pushSpy = jest.spyOn(router.actions, 'push')
            logic = paymentEntryLogic()
            logic.mount()
            logic.actions.beginPaymentFlow(organizationLogic.values.currentOrganization!.id, '/project/1/replay')
            logic.actions.showPaymentEntryModal()
        })

        afterEach(() => {
            pushSpy.mockRestore()
        })

        it('still polls and refreshes when the modal closes while the confirmation is pending', async () => {
            const statusRequest = mockPaidOrganization(['success'])
            const confirmation = deferred<unknown>()
            logic.actions.confirmPayment(
                fakeStripe(() => confirmation.promise),
                fakeElements
            )
            logic.actions.hidePaymentEntryModal()
            confirmation.resolve({ paymentIntent: { id: 'pi_submitted' } })
            await waitFor(() => expect(statusRequest).toHaveBeenCalledTimes(1))
            await expectLogic(logic).toFinishAllListeners()
            expectPaidOrganizationApplied()
        })

        it('still refreshes when the modal closes while the status is loading', async () => {
            const statusRequest = mockPaidOrganization(['loading', 'success'])
            const retries = holdStatusRetries()
            try {
                logic.actions.confirmPayment(
                    fakeStripe(async () => ({ paymentIntent: { id: 'pi_submitted' } })),
                    fakeElements
                )
                await expectLogic(logic).toFinishAllListeners()
                expect(statusRequest).toHaveBeenCalledTimes(1)
                logic.actions.hidePaymentEntryModal()
                await retries.fire()
                await expectLogic(logic).toFinishAllListeners()
            } finally {
                retries.restore()
            }
            expect(statusRequest).toHaveBeenCalledTimes(2)
            expectPaidOrganizationApplied()
        })

        it('ends the flow when the modal closes after the card is declined', async () => {
            logic.actions.setClientSecret('secret_submitted')
            logic.actions.confirmPayment(
                fakeStripe(async () => ({ error: { message: 'Your card was declined.' } })),
                fakeElements
            )
            await expectLogic(logic).toFinishAllListeners()
            // The card form stays so the decline shows and another card can be tried.
            expect(logic.values).toMatchObject({
                stripeError: 'Your card was declined.',
                isLoading: false,
                clientSecret: 'secret_submitted',
            })
            logic.actions.hidePaymentEntryModal()
            expect(logic.values.paymentFlow).toBe(null)
        })

        it('closes the modal and clears the card form after the payment completes', async () => {
            mockPaidOrganization(['success'])
            logic.actions.setClientSecret('secret_submitted')
            submitCard()
            await expectLogic(logic).toFinishAllListeners()
            expectPaidOrganizationApplied()
            expect(logic.values).toMatchObject({ paymentEntryModalOpen: false, isLoading: false, clientSecret: null })
        })

        it('refuses a second start while the status is loading and still completes the first payment', async () => {
            const statusRequest = mockPaidOrganization(['loading', 'success'])
            const retries = holdStatusRetries()
            try {
                submitCard()
                await expectLogic(logic).toFinishAllListeners()
                logic.actions.hidePaymentEntryModal()
                startAgainAndExpectRefusal()
                await retries.fire()
                await expectLogic(logic).toFinishAllListeners()
            } finally {
                retries.restore()
            }
            expect(statusRequest).toHaveBeenCalledTimes(2)
            expectPaidOrganizationApplied()
            expect(pushSpy).toHaveBeenCalledTimes(1)
        })

        it('refuses a second start while the confirmation is pending and still completes the first payment', async () => {
            const statusRequest = mockPaidOrganization(['success'])
            const confirmation = deferred<unknown>()
            logic.actions.confirmPayment(
                fakeStripe(() => confirmation.promise),
                fakeElements
            )
            logic.actions.hidePaymentEntryModal()
            startAgainAndExpectRefusal()
            confirmation.resolve({ paymentIntent: { id: 'pi_submitted' } })
            await waitFor(() => expect(statusRequest).toHaveBeenCalledTimes(1))
            await expectLogic(logic).toFinishAllListeners()
            expectPaidOrganizationApplied()
            expect(pushSpy).toHaveBeenCalledTimes(1)
        })

        it('lets the next start begin after a failed payment is closed', async () => {
            mockPaidOrganization(['failed'])
            submitCard()
            await expectLogic(logic).toFinishAllListeners()
            logic.actions.hidePaymentEntryModal()
            logic.actions.startPaymentEntryFlow(null, '/project/1/replay')
            expect(toastInfoSpy).not.toHaveBeenCalled()
            expect(logic.values.paymentEntryModalOpen).toBe(true)
        })

        it('lets an add-on purchase start after the payment completes', async () => {
            mockPaidOrganization(['success'])
            const activate = jest.fn(() => [200, { success: false, error: 'Stopped before charging' }])
            useMocks({ post: { '/api/billing/activate': activate } })
            submitCard()
            await expectLogic(logic).toFinishAllListeners()
            expectPaidOrganizationApplied()
            await expectLogic(logic, () => logic.actions.upgradeProducts('scale:scale', null)).toFinishAllListeners()
            expect(toastInfoSpy).not.toHaveBeenCalled()
            expect(activate).toHaveBeenCalledTimes(1)
        })

        it('lets the next start begin after a payment for another organization completes', async () => {
            const organization = organizationLogic.values.currentOrganization!
            mockPaidOrganization(['success'])
            submitCard()
            organizationLogic.actions.loadCurrentOrganizationSuccess({ ...organization, id: OTHER_ORGANIZATION_ID })
            await expectLogic(logic).toFinishAllListeners()
            expect(logic.values.completedPaymentOrganization?.id).toBe(organization.id)
            logic.actions.hidePaymentEntryModal()
            logic.actions.startPaymentEntryFlow(null, '/project/1/replay')
            expect(toastInfoSpy).not.toHaveBeenCalled()
            expect(logic.values.paymentEntryModalOpen).toBe(true)
        })

        it('refuses an add-on purchase while the status is loading and still completes the first payment', async () => {
            const statusRequest = mockPaidOrganization(['loading', 'success'])
            const activate = jest.fn(() => [200, { success: true }])
            useMocks({ post: { '/api/billing/activate': activate } })
            const retries = holdStatusRetries()
            try {
                submitCard()
                await expectLogic(logic).toFinishAllListeners()
                logic.actions.hidePaymentEntryModal()
                const flow = logic.values.paymentFlow
                await expectLogic(logic, () =>
                    logic.actions.upgradeProducts('scale:scale', null)
                ).toFinishAllListeners()
                expect(toastInfoSpy).toHaveBeenCalledWith("We're still confirming your last payment.")
                expect(activate).not.toHaveBeenCalled()
                expect(logic.values.paymentFlow).toBe(flow)
                await retries.fire()
                await expectLogic(logic).toFinishAllListeners()
            } finally {
                retries.restore()
            }
            expect(statusRequest).toHaveBeenCalledTimes(2)
            expectPaidOrganizationApplied()
            expect(pushSpy).toHaveBeenCalledTimes(1)
        })

        it('completes once when two status checks for the same payment both succeed', async () => {
            const organization = organizationLogic.values.currentOrganization!
            const status = deferred<[number, unknown]>()
            let statusChecks = 0
            useMocks({
                get: { [`/api/organizations/${organization.id}`]: () => [200, organization] },
                post: {
                    '/api/billing/activate/authorize/status': () => {
                        statusChecks++
                        return status.promise
                    },
                },
            })
            logic.actions.confirmPayment(
                fakeStripe(async () => ({ paymentIntent: { id: 'pi_submitted' } })),
                fakeElements
            )
            await waitFor(() => expect(statusChecks).toBe(1))
            logic.actions.pollAuthorizationStatus('pi_submitted')
            await waitFor(() => expect(statusChecks).toBe(2))
            status.resolve([200, { status: 'success' }])
            await expectLogic(logic).toFinishAllListeners()
            expect(pushSpy).toHaveBeenCalledTimes(1)
        })

        it.each([
            ['success', [200, { status: 'success' }]],
            ['failed', [200, { status: 'failed', error: 'Your card was declined.' }]],
            ['error', [500, { detail: 'Server error' }]],
        ])('does not poll again when the tab becomes visible after a %s outcome', async (_, finalResponse) => {
            const responses: unknown[] = [[200, { status: 'loading' }], finalResponse]
            const statusRequest = jest.fn(() => responses.shift() ?? [200, { status: 'loading' }])
            useMocks({ post: { '/api/billing/activate/authorize/status': statusRequest } })
            const retries = holdStatusRetries()
            try {
                await expectLogic(logic, () =>
                    logic.actions.pollAuthorizationStatus('pi_submitted')
                ).toFinishAllListeners()
                await retries.fire()
                await expectLogic(logic).toFinishAllListeners()
                expect(statusRequest).toHaveBeenCalledTimes(2)
                setDocumentHidden(true)
                setDocumentHidden(false)
                await retries.fire()
                await expectLogic(logic).toFinishAllListeners()
                expect(statusRequest).toHaveBeenCalledTimes(2)
            } finally {
                retries.restore()
                delete (document as { hidden?: boolean }).hidden
            }
        })
    })

    describe('authorization status failures', () => {
        let captureSpy: jest.SpyInstance

        beforeEach(() => {
            captureSpy = jest.spyOn(posthog, 'captureException').mockImplementation(() => undefined as any)
            logic = paymentEntryLogic()
            logic.mount()
            logic.actions.beginPaymentFlow('00000000-0000-4000-8000-000000000001', '/project/1/replay')
            logic.actions.setClientSecret('secret_test')
        })

        const submitCard = (): void =>
            logic.actions.confirmPayment(
                fakeStripe(async () => ({ paymentIntent: { id: 'pi_test' } })),
                fakeElements
            )

        const expectFlowEnded = (): void => {
            expect(logic.values).toMatchObject({
                isLoading: false,
                clientSecret: null,
                redirectPath: null,
                paymentSubmitted: false,
            })
        }

        afterEach(() => {
            captureSpy.mockRestore()
        })

        const capturedError = (): { message: string; cause: string } => {
            expect(captureSpy).toHaveBeenCalledTimes(1)
            const [error] = captureSpy.mock.calls[0]
            return { message: error.message, cause: error.cause.message }
        }

        it('reports a failed authorization', async () => {
            useMocks({
                post: {
                    '/api/billing/activate/authorize/status': () => [
                        200,
                        { status: 'failed', error: 'Your card was declined.' },
                    ],
                },
            })
            await expectLogic(logic, () => submitCard()).toFinishAllListeners()
            expect(logic.values.apiError).toBe('Your card was declined.')
            expect(capturedError()).toEqual({
                message: 'payment entry api error - authorization status failed',
                cause: 'Your card was declined.',
            })
            expectFlowEnded()
        })

        it('reports a status check that times out', async () => {
            const statusRequest = jest.fn(() => [200, { status: 'loading' }])
            useMocks({ post: { '/api/billing/activate/authorize/status': statusRequest } })
            const retries = holdStatusRetries()
            try {
                await expectLogic(logic, () => submitCard()).toFinishAllListeners()
                while (statusRequest.mock.calls.length < 30) {
                    await retries.fire()
                    await expectLogic(logic).toFinishAllListeners()
                }
            } finally {
                retries.restore()
            }
            expect(statusRequest).toHaveBeenCalledTimes(30)
            expect(logic.values.apiError).toBe('Payment status check timed out')
            expect(capturedError()).toEqual({
                message: 'payment entry api error - authorization status timed out',
                cause: 'Payment failed. Please try again.',
            })
            expectFlowEnded()
        })

        it('reports a status check that errors', async () => {
            useMocks({ post: { '/api/billing/activate/authorize/status': () => [500, { detail: 'Server error' }] } })
            await expectLogic(logic, () => submitCard()).toFinishAllListeners()
            expect(logic.values.apiError).toBe('Failed to complete. Please refresh the page and try again.')
            expect(capturedError().message).toBe('payment entry api error')
            expectFlowEnded()
        })
    })

    describe('a payment step that settles after it was superseded', () => {
        type Outcome = 'resolves' | 'rejects'
        interface PendingStep {
            start: () => void
            requested: () => boolean
            settle: (outcome: Outcome) => void
        }

        const pendingRequest = (method: 'get' | 'post', url: string, body: unknown): Omit<PendingStep, 'start'> => {
            const response = deferred<[number, unknown]>()
            let requested = false
            const handlers = {
                [url]: () => {
                    requested = true
                    return response.promise
                },
            }
            useMocks(method === 'get' ? { get: handlers } : { post: handlers })
            return {
                requested: () => requested,
                settle: (outcome) =>
                    response.resolve(outcome === 'resolves' ? [200, body] : [500, { detail: 'Server error' }]),
            }
        }

        const steps: Record<string, (organizationId: string) => PendingStep> = {
            'subscription activation': () => ({
                ...pendingRequest('post', '/api/billing/activate', { success: true }),
                start: () => logic.actions.startPaymentEntryFlow(),
            }),
            'add-on activation': () => ({
                ...pendingRequest('post', '/api/billing/activate', { success: true }),
                start: () => logic.actions.upgradeProducts('scale:scale', null),
            }),
            'card authorization': (organizationId) => ({
                ...pendingRequest('post', '/api/billing/activate/authorize', { clientSecret: 'secret_stale' }),
                start: () => {
                    logic.actions.beginPaymentFlow(organizationId)
                    logic.actions.initiateAuthorization()
                },
            }),
            'card confirmation': (organizationId) => {
                const confirmation = deferred<unknown>()
                let requested = false
                const stripe = fakeStripe(() => {
                    requested = true
                    return confirmation.promise
                })
                return {
                    start: () => {
                        logic.actions.beginPaymentFlow(organizationId)
                        logic.actions.confirmPayment(stripe, fakeElements)
                    },
                    requested: () => requested,
                    settle: (outcome) =>
                        outcome === 'resolves'
                            ? confirmation.resolve({ paymentIntent: { id: 'pi_stale' } })
                            : confirmation.reject(new Error('Network error')),
                }
            },
            'status check': (organizationId) => ({
                ...pendingRequest('post', '/api/billing/activate/authorize/status', { status: 'success' }),
                start: () => {
                    logic.actions.beginPaymentFlow(organizationId)
                    logic.actions.pollAuthorizationStatus('pi_stale')
                },
            }),
            'billing read': (organizationId) => ({
                ...pendingRequest('get', '/api/billing', { subscription_level: 'paid', customer_id: 'cus_stale' }),
                start: () => {
                    logic.actions.beginPaymentFlow(organizationId)
                    logic.actions.completePaymentFlow(null, { success: true })
                },
            }),
            'organization read': (organizationId) => ({
                ...pendingRequest('get', `/api/organizations/${organizationId}`, {
                    ...organizationLogic.values.currentOrganization,
                    name: 'Stale name',
                }),
                start: () => {
                    logic.actions.beginPaymentFlow(organizationId)
                    logic.actions.completePaymentFlow(null, { success: true })
                },
            }),
        }

        let captureSpy: jest.SpyInstance
        let pushSpy: jest.SpyInstance

        beforeEach(async () => {
            await seedBilling({ customer_id: 'cus_test', subscription_level: 'free' })
            captureSpy = jest.spyOn(posthog, 'captureException').mockImplementation(() => undefined as any)
            pushSpy = jest.spyOn(router.actions, 'push')
            logic = paymentEntryLogic()
            logic.mount()
        })

        afterEach(() => {
            captureSpy.mockRestore()
            pushSpy.mockRestore()
        })

        const snapshot = (): Record<string, unknown> => ({
            payment: Object.fromEntries(
                Object.keys(paymentEntryLogic.selectors).map((key) => [key, (logic.values as any)[key]])
            ),
            billing: billingLogic.values.billing,
            organization: organizationLogic.values.currentOrganization,
            user: userLogic.values.user,
        })

        const sideEffects = (): Record<string, unknown[]> => ({
            toasts: toastErrorSpy.mock.calls,
            captures: captureSpy.mock.calls,
            navigations: pushSpy.mock.calls,
        })

        const settleLate = async (
            step: PendingStep,
            outcome: Outcome,
            supersede: () => void
        ): Promise<{ before: unknown; after: unknown; sideEffects: Record<string, unknown[]> }> => {
            step.start()
            await waitFor(() => expect(step.requested()).toBe(true))
            supersede()
            const before = snapshot()
            step.settle(outcome)
            await expectLogic(logic).toFinishAllListeners()
            return { before, after: snapshot(), sideEffects: sideEffects() }
        }
        const NO_SIDE_EFFECTS = { toasts: [], captures: [], navigations: [] }

        const cases = Object.keys(steps).flatMap((name) =>
            (['resolves', 'rejects'] as const).map((outcome) => [name, outcome] as const)
        )

        it.each(cases)('%s that %s after a new flow starts changes nothing', async (name, outcome) => {
            const step = steps[name](organizationLogic.values.currentOrganization!.id)
            const { before, after, sideEffects } = await settleLate(step, outcome, () =>
                logic.actions.beginPaymentFlow(OTHER_ORGANIZATION_ID)
            )
            expect(after).toEqual(before)
            expect(sideEffects).toEqual(NO_SIDE_EFFECTS)
        })

        it('status check retry that fires after a new flow starts changes nothing', async () => {
            const statuses = ['loading', 'success']
            const statusRequest = jest.fn(() => [200, { status: statuses.shift() }])
            useMocks({ post: { '/api/billing/activate/authorize/status': statusRequest } })
            const retries = holdStatusRetries()
            try {
                logic.actions.beginPaymentFlow(organizationLogic.values.currentOrganization!.id)
                await expectLogic(logic, () => logic.actions.pollAuthorizationStatus('pi_stale')).toFinishAllListeners()
                logic.actions.beginPaymentFlow(OTHER_ORGANIZATION_ID)
                const before = snapshot()
                await retries.fire()
                await expectLogic(logic).toFinishAllListeners()
                expect(snapshot()).toEqual(before)
            } finally {
                retries.restore()
            }
            expect(statusRequest).toHaveBeenCalledTimes(1)
            expect(sideEffects()).toEqual(NO_SIDE_EFFECTS)
        })

        it.each(['resolves', 'rejects'] as const)(
            'card authorization that %s after the modal is cancelled changes nothing',
            async (outcome) => {
                const step = steps['card authorization'](organizationLogic.values.currentOrganization!.id)
                const { before, after, sideEffects } = await settleLate(step, outcome, () =>
                    logic.actions.hidePaymentEntryModal()
                )
                expect(after).toEqual(before)
                expect(sideEffects).toEqual(NO_SIDE_EFFECTS)
                expect(logic.values.paymentFlow).toBe(null)
            }
        )

        it.each(['resolves', 'rejects'] as const)(
            'card authorization that %s after the logic unmounts reports nothing',
            async (outcome) => {
                const step = steps['card authorization'](organizationLogic.values.currentOrganization!.id)
                step.start()
                await waitFor(() => expect(step.requested()).toBe(true))
                logic.unmount()
                try {
                    step.settle(outcome)
                    await new Promise((resolve) => setTimeout(resolve, 0))
                    expect(toastErrorSpy).not.toHaveBeenCalled()
                    expect(captureSpy).not.toHaveBeenCalled()
                } finally {
                    logic.mount()
                }
            }
        )
    })
})
