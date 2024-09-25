import { kea } from 'kea'
import api from 'lib/api'
import { urls } from 'scenes/urls'

import type { paymentEntryLogicType } from './PaymentEntryLogicType'

export const paymentEntryLogic = kea<paymentEntryLogicType>({
    path: ['scenes', 'billing', 'PaymentEntryLogic'],

    actions: {
        setClientSecret: (clientSecret) => ({ clientSecret }),
        setLoading: (loading) => ({ loading }),
        setError: (error) => ({ error }),
        initiateAuthorization: (redirectPath: string) => ({ redirectPath }),
        pollAuthorizationStatus: true,
        setAuthorizationStatus: (status: string | null) => ({ status }),
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

    listeners: ({ actions }) => ({
        initiateAuthorization: async (redirectPath: string) => {
            actions.setLoading(true)
            actions.setError(null)
            try {
                const response = await api.create('api/billing/activate/authorize')
                actions.setClientSecret(response.clientSecret)
                actions.setRedirectPath(redirectPath)
                actions.setLoading(false)
            } catch (error) {
                actions.setError('Failed to initialize payment')
            }
        },

        pollAuthorizationStatus: async () => {
            const pollInterval = 2000 // Poll every 2 seconds
            const maxAttempts = 30 // Max 1 minute of polling (30 * 2 seconds)
            let attempts = 0

            const poll = async (): Promise<void> => {
                try {
                    const urlParams = new URLSearchParams(window.location.search)
                    const paymentIntentId = urlParams.get('payment_intent')
                    const response = await api.create('api/billing/activate/authorize/status', {
                        payment_intent_id: paymentIntentId,
                    })
                    const status = response.status

                    actions.setAuthorizationStatus(status)

                    if (status === 'success') {
                        if (actions.redirectPath) {
                            window.location.href = actions.redirectPath
                        } else {
                            window.location.href = urls.organizationBilling()
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
