import { actions, afterMount, connect, kea, listeners, path, reducers } from 'kea'
import { router } from 'kea-router'
import posthog from 'posthog-js'

import api from 'lib/api'
import { organizationLogic } from 'scenes/organizationLogic'
import { userLogic } from 'scenes/userLogic'

import { BillingProductV2Type } from '~/types'

import { billingLogic } from './billingLogic'
import { billingProductLogic } from './billingProductLogic'
import type { paymentEntryLogicType } from './paymentEntryLogicType'

export const paymentEntryLogic = kea<paymentEntryLogicType>([
    path(['scenes', 'billing', 'PaymentEntryLogic']),
    connect({
        actions: [userLogic, ['loadUser'], organizationLogic, ['loadCurrentOrganization']],
    }),
    actions({
        setClientSecret: (clientSecret) => ({ clientSecret }),
        setLoading: (loading) => ({ loading }),
        setStripeError: (error) => ({ error }),
        setApiError: (error) => ({ error }),
        clearErrors: true,
        initiateAuthorization: true,
        pollAuthorizationStatus: (paymentIntentId?: string) => ({ paymentIntentId }),
        setAuthorizationStatus: (status: string | null) => ({ status }),
        startPaymentEntryFlow: (product?: BillingProductV2Type | null, redirectPath?: string | null) => ({
            product,
            redirectPath,
        }),
        showPaymentEntryModal: true,
        hidePaymentEntryModal: true,
        setRedirectPath: (redirectPath: string | null) => ({ redirectPath }),
    }),
    reducers({
        clientSecret: [
            null,
            {
                setClientSecret: (_, { clientSecret }) => clientSecret,
            },
        ],
        isLoading: [
            false,
            {
                setLoading: (_, { loading }) => loading,
            },
        ],
        stripeError: [
            null,
            {
                setStripeError: (_, { error }) => error,
                clearErrors: () => null,
            },
        ],
        apiError: [
            null,
            {
                setApiError: (_, { error }) => error,
                clearErrors: () => null,
            },
        ],
        authorizationStatus: [
            null as string | null,
            {
                setAuthorizationStatus: (_, { status }) => status,
            },
        ],
        paymentEntryModalOpen: [
            false,
            {
                showPaymentEntryModal: () => true,
                hidePaymentEntryModal: () => false,
            },
        ],
        redirectPath: [
            null as string | null,
            {
                setRedirectPath: (_, { redirectPath }) => redirectPath,
            },
        ],
    }),
    listeners(({ actions, values }) => ({
        startPaymentEntryFlow: async ({ product, redirectPath }) => {
            const { billing } = billingLogic.values

            if (billing?.customer_id) {
                // Returning customer — call POST API to activate subscription
                actions.setLoading(true)
                if (product) {
                    const theBillingProductLogic = billingProductLogic({ product })
                    theBillingProductLogic.actions.setBillingProductLoading(product.type)
                }

                try {
                    const body: Record<string, string> = { products: 'all_products:' }
                    if (product?.type) {
                        body.intent_product = product.type
                    }
                    const response = await api.create('api/billing/activate', body)

                    if (response.success) {
                        await billingLogic.asyncActions.loadBilling()
                        if (redirectPath) {
                            const url = new URL(redirectPath, window.location.origin)
                            const searchParams = Object.fromEntries(url.searchParams.entries())
                            router.actions.push(url.pathname, { ...searchParams, upgraded: 'true' })
                        } else {
                            router.actions.push(router.values.location.pathname, {
                                ...router.values.searchParams,
                                upgraded: 'true',
                            })
                        }
                        actions.loadCurrentOrganization()
                        actions.loadUser()
                    } else if (response.must_setup_payment) {
                        // Card invalid or missing — show modal (same as new customer flow)
                        actions.setRedirectPath(redirectPath || null)
                        actions.showPaymentEntryModal()
                    } else {
                        actions.setApiError(response.error || 'Failed to activate subscription')
                    }
                } catch (error) {
                    posthog.captureException(
                        new Error('payment entry api error - activate subscription error', { cause: error })
                    )
                    actions.setApiError('Failed to activate subscription. Please try again.')
                } finally {
                    actions.setLoading(false)
                    if (product) {
                        const { setBillingProductLoading } = billingProductLogic({ product }).actions
                        setBillingProductLoading(null)
                    }
                }
                return
            }

            // New customer — show the payment modal
            actions.setRedirectPath(redirectPath || null)
            actions.showPaymentEntryModal()
        },
        initiateAuthorization: async () => {
            actions.setLoading(true)
            actions.clearErrors()
            try {
                const response = await api.create('api/billing/activate/authorize')
                actions.setClientSecret(response.clientSecret)
                actions.setLoading(false)
            } catch (error) {
                posthog.captureException(
                    new Error('payment entry api error - initiate authorization error', { cause: error })
                )
                actions.setApiError('Failed to initialize payment')
                actions.setLoading(false)
            }
        },

        pollAuthorizationStatus: ({ paymentIntentId }) => {
            const pollInterval = 2000 // Poll every 2 seconds
            const maxAttempts = 30 // Max 1 minute of polling (30 * 2 seconds)

            let attempts = 0
            const poll = async (): Promise<void> => {
                try {
                    const urlParams = new URLSearchParams(window.location.search)
                    const searchPaymentIntentId = urlParams.get('payment_intent')
                    const response = await api.create('api/billing/activate/authorize/status', {
                        payment_intent_id: paymentIntentId || searchPaymentIntentId,
                    })
                    const status = response.status
                    const errorMessage = response.error || 'Payment failed. Please try again.'

                    actions.setAuthorizationStatus(status)

                    if (status === 'success') {
                        // Load before doing anything to reload in entitlements on the organization
                        await billingLogic.asyncActions.loadBilling()
                        if (values.redirectPath) {
                            const url = new URL(values.redirectPath, window.location.origin)
                            const searchParams = Object.fromEntries(url.searchParams.entries())
                            router.actions.push(url.pathname, { ...searchParams, success: true })
                        } else {
                            router.actions.push(router.values.location.pathname, {
                                ...router.values.searchParams,
                                success: true,
                            })
                        }
                        actions.loadCurrentOrganization()
                        actions.loadUser()
                        actions.hidePaymentEntryModal()
                        return
                    } else if (status === 'failed') {
                        actions.setApiError(errorMessage)
                        posthog.captureException(
                            new Error('payment entry api error - authorization status failed', {
                                cause: new Error(errorMessage),
                            })
                        )
                        return
                    }

                    attempts++
                    if (attempts < maxAttempts) {
                        setTimeout(() => void poll(), pollInterval)
                    } else {
                        actions.setApiError('Payment status check timed out')
                        posthog.captureException(
                            new Error('payment entry api error - authorization status timed out', {
                                cause: new Error(errorMessage),
                            })
                        )
                    }
                } catch (error) {
                    actions.setStripeError('Failed to complete. Please refresh the page and try again.')
                    posthog.captureException(new Error('payment entry api error', { cause: error }))
                } finally {
                    actions.setLoading(false)
                    actions.setClientSecret(null)
                    actions.setRedirectPath(null)
                }
            }

            // Fire and forget polling, it'll handle cancelation and stopping itself when it reaches max attempts
            poll()
        },

        hidePaymentEntryModal: () => {
            // Clear client secret when modal is closed to ensure a fresh one is used next time
            actions.setClientSecret(null)
            actions.clearErrors()
        },
    })),
    afterMount(({ actions }) => {
        // In case the user gets redirected back to the app after completing payment on Stripe's hosted page,
        // we need to set up the proper `redirectPath` so that polling sends us to the right place after successful payment
        const urlParams = new URLSearchParams(window.location.search)
        const postRedirectPath = urlParams.get('postRedirectPath')
        if (postRedirectPath) {
            actions.setRedirectPath(postRedirectPath)
        }
    }),
])
