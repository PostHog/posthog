import { kea } from 'kea'
import { router } from 'kea-router'
import api from 'lib/api'
import { organizationLogic } from 'scenes/organizationLogic'
import { userLogic } from 'scenes/userLogic'

import { BillingProductV2Type } from '~/types'

import { getUpgradeProductLink } from './billing-utils'
import { billingLogic } from './billingLogic'
import { billingProductLogic } from './billingProductLogic'
import type { paymentEntryLogicType } from './paymentEntryLogicType'

export const paymentEntryLogic = kea<paymentEntryLogicType>({
    path: ['scenes', 'billing', 'PaymentEntryLogic'],

    connect: {
        actions: [userLogic, ['loadUser'], organizationLogic, ['loadCurrentOrganization']],
    },

    actions: {
        setClientSecret: (clientSecret) => ({ clientSecret }),
        setLoading: (loading) => ({ loading }),
        setError: (error) => ({ error }),
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
    },

    reducers: {
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
        error: [
            null,
            {
                setError: (_, { error }) => error,
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
    },

    listeners: ({ actions, values }) => ({
        startPaymentEntryFlow: ({ product, redirectPath }) => {
            const { billing } = billingLogic.values

            // TODO(@zach): we should also check that they have a valid default payment method
            if (billing?.customer_id) {
                // If customer_id exists, redirect to the upgrade product link
                // because they already have an active stripe customer
                if (product) {
                    const { setBillingProductLoading } = billingProductLogic({ product }).actions
                    setBillingProductLoading(product.type)
                }
                window.location.href = getUpgradeProductLink({
                    product: product || undefined,
                    redirectPath: redirectPath || undefined,
                })
                return
            }

            // Otherwise, proceed with showing the modal
            actions.setRedirectPath(redirectPath || null)
            actions.showPaymentEntryModal()
        },
        initiateAuthorization: async () => {
            actions.setLoading(true)
            actions.setError(null)
            try {
                const response = await api.create('api/billing/activate/authorize')
                actions.setClientSecret(response.clientSecret)
                actions.setLoading(false)
            } catch (error) {
                actions.setError('Failed to initialize payment')
            }
        },

        pollAuthorizationStatus: async ({ paymentIntentId }, breakpoint) => {
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
                            window.location.pathname = values.redirectPath
                        } else {
                            // Push success to the url
                            await breakpoint(1000)
                            router.actions.push(router.values.location.pathname, {
                                ...router.values.searchParams,
                                success: true,
                            })
                            actions.loadCurrentOrganization()
                            actions.loadUser()
                            actions.hidePaymentEntryModal()
                        }
                        return
                    } else if (status === 'failed') {
                        actions.setError(errorMessage)
                        return
                    }

                    attempts++
                    if (attempts < maxAttempts) {
                        setTimeout(() => void poll(), pollInterval)
                    } else {
                        actions.setError('Payment status check timed out')
                    }
                } catch (error) {
                    actions.setError('Failed to complete. Please refresh the page and try again.')
                } finally {
                    // Reset the state
                    actions.setLoading(false)
                    actions.setAuthorizationStatus(null)
                    actions.setClientSecret(null)
                    actions.setRedirectPath(null)
                }
            }

            await poll()
        },
    }),
})
