import { Elements, PaymentElement, useElements, useStripe } from '@stripe/react-stripe-js'
import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { useEffect, useState } from 'react'

import { LemonBanner, LemonButton, LemonModal } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { paymentEntryLogic } from './paymentEntryLogic'

const stripeJs = async (): Promise<typeof import('@stripe/stripe-js')> => await import('@stripe/stripe-js')

export const PaymentForm = (): JSX.Element => {
    const { stripeError, isLoading, redirectPath } = useValues(paymentEntryLogic)
    const { setStripeError, clearErrors, hidePaymentEntryModal, pollAuthorizationStatus, setLoading } =
        useActions(paymentEntryLogic)

    const stripe = useStripe()
    const elements = useElements()

    const handleSubmit = async (event: React.MouseEvent<HTMLElement>): Promise<void> => {
        clearErrors()
        event.preventDefault()
        // Stripe.js never became usable: no publishable key, a blocked script, or a load failure.
        // Returning quietly leaves a button that does nothing at all, which reads as a broken app
        // and gives neither the user nor a support ticket anything to go on.
        if (!stripe || !elements) {
            setStripeError('Payment form could not be loaded. Disable any ad blocker, reload the page, and try again.')
            posthog.captureException(new Error('payment entry stripe unavailable'), {
                has_stripe: !!stripe,
                has_elements: !!elements,
                has_public_key: !!window.STRIPE_PUBLIC_KEY,
            })
            return
        }
        setLoading(true)

        const returnUrl = `${window.location.origin}${urls.billingAuthorizationStatus()}`
        const queryParams = redirectPath ? `?postRedirectPath=${encodeURIComponent(redirectPath)}` : ''
        const result = await stripe.confirmPayment({
            elements,
            confirmParams: { return_url: `${returnUrl}${queryParams}` },
            redirect: 'if_required',
        })

        if (result.error) {
            setLoading(false)
            setStripeError(result.error.message)
            posthog.captureException(new Error('payment entry stripe error', { cause: result.error }))
        } else {
            pollAuthorizationStatus(result.paymentIntent.id)
        }
    }

    return (
        <div>
            <PaymentElement />
            <p className="text-xs text-secondary mt-0.5">
                A temporary $0.50 authorization hold will be placed on your card to verify it. This hold will be
                automatically released within 7 days and you will not be charged.
            </p>
            {stripeError && <LemonBanner type="error">{stripeError}</LemonBanner>}
            <div className="flex justify-end deprecated-space-x-2 mt-2">
                <LemonButton disabled={isLoading} type="secondary" onClick={hidePaymentEntryModal}>
                    Cancel
                </LemonButton>
                <LemonButton loading={isLoading} type="primary" onClick={(event) => void handleSubmit(event)}>
                    Submit
                </LemonButton>
            </div>
        </div>
    )
}

export const PaymentEntryModal = (): JSX.Element => {
    const { clientSecret, paymentEntryModalOpen, apiError } = useValues(paymentEntryLogic)
    const { hidePaymentEntryModal, initiateAuthorization } = useActions(paymentEntryLogic)
    const [stripePromise, setStripePromise] = useState<any>(null)

    useEffect(() => {
        // Only load Stripe.js when the modal is opened
        if (paymentEntryModalOpen && !stripePromise) {
            const loadStripeJs = async (): Promise<void> => {
                const { loadStripe } = await stripeJs()
                const publicKey = window.STRIPE_PUBLIC_KEY!
                setStripePromise(await loadStripe(publicKey))
            }
            // `loadStripe` rejects outright when the key is missing (an instance without Stripe
            // configured, e.g. local dev), so without a catch this is an unhandled rejection and the
            // only symptom is an inert form.
            void loadStripeJs().catch((error) => {
                posthog.captureException(new Error('payment entry stripe load failed', { cause: error }))
            })
        }
    }, [paymentEntryModalOpen, stripePromise])

    useEffect(() => {
        if (paymentEntryModalOpen) {
            initiateAuthorization()
        }
    }, [paymentEntryModalOpen, initiateAuthorization])

    return (
        <LemonModal
            onClose={hidePaymentEntryModal}
            width="max(44vw)"
            isOpen={paymentEntryModalOpen}
            title="Add your payment details to subscribe"
            description=""
        >
            <div>
                {clientSecret ? (
                    <Elements stripe={stripePromise} options={{ clientSecret }}>
                        <PaymentForm />
                    </Elements>
                ) : apiError ? (
                    <div className="flex flex-col gap-2 my-2">
                        <p className="text-md">
                            We could not complete your upgrade at this time. Please review the error below and contact
                            support if you need help.
                        </p>
                        <LemonBanner type="error">{apiError}</LemonBanner>
                    </div>
                ) : (
                    <div className="min-h-80 flex flex-col justify-center items-center">
                        <img src="/static/payment-loading.gif" alt="" aria-hidden="true" className="h-20 w-20" />
                        <p className="text-secondary text-md mt-4">We're contacting the hedgehogs for approval.</p>
                    </div>
                )}
            </div>
        </LemonModal>
    )
}
