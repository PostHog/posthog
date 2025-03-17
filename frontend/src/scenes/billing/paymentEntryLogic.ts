import { kea } from 'kea'
import { router } from 'kea-router'
import api from 'lib/api'
import { organizationLogic } from 'scenes/organizationLogic'
import { userLogic } from 'scenes/userLogic'

import { billingLogic } from './billingLogic'
import type { paymentEntryLogicType } from './paymentEntryLogicType'

export const paymentEntryLogic = kea<paymentEntryLogicType>({
    path: ['scenes', 'billing', 'PaymentEntryLogic'],

    connect: {
        actions: [
            userLogic,
            ['loadUser'],
            organizationLogic,
            ['loadCurrentOrganization'],
            billingLogic,
            ['loadBilling'],
        ],
    },

    actions: {
        setClientSecret: (clientSecret) => ({ clientSecret }),
        setLoading: (loading) => ({ loading }),
        setError: (error) => ({ error }),
        initiateAuthorization: true,
        pollAuthorizationStatus: (paymentIntentId?: string) => ({ paymentIntentId }),
        setAuthorizationStatus: (status: string | null) => ({ status }),
        showPaymentEntryModal: (redirectPath?: string | null) => ({ redirectPath }),
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
                showPaymentEntryModal: (state, { redirectPath }) => redirectPath ?? state,
            },
        ],
    },

    listeners: ({ actions, values }) => ({
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

        pollAuthorizationStatus: async ({ paymentIntentId }) => {
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

                    actions.setAuthorizationStatus(status)

                    if (status === 'success') {
                        if (values.redirectPath) {
                            window.location.pathname = values.redirectPath
                        } else {
                            // Push success to the url
                            router.actions.push(router.values.location.pathname, {
                                ...router.values.searchParams,
                                success: true,
                            })
                            actions.loadBilling()
                            actions.loadCurrentOrganization()
                            actions.loadUser()
                            actions.hidePaymentEntryModal()
                        }
                        return
                    } else if (status === 'failed') {
                        actions.setError('Payment failed')
                        return
                    }

                    attempts++
                    if (attempts < maxAttempts) {
                        setTimeout(() => void poll(), pollInterval)
                    } else {
                        actions.setError('Payment status check timed out')
                    }
                } catch (error) {
                    actions.setError('Failed to check payment status')
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
