import { LemonBanner, LemonButton, LemonModal } from '@posthog/lemon-ui'
import { Elements, PaymentElement, useElements, useStripe } from '@stripe/react-stripe-js'
import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { useEffect, useState } from 'react'

import { paymentEntryLogic } from './paymentEntryLogic'

const stripeJs = async (): Promise<typeof import('@stripe/stripe-js')> => await import('@stripe/stripe-js')

export const PaymentForm = (): JSX.Element => {
    const { stripeError, isLoading } = useValues(paymentEntryLogic)
    const { setStripeError, clearErrors, hidePaymentEntryModal, pollAuthorizationStatus, setLoading } =
        useActions(paymentEntryLogic)

    const stripe = useStripe()
    const elements = useElements()

    const handleSubmit = async (event: React.MouseEvent<HTMLElement>): Promise<void> => {
        clearErrors()
        event.preventDefault()
        if (!stripe || !elements) {
            return
        }
        setLoading(true)
        const result = await stripe.confirmPayment({
            elements,
            confirmParams: {
                return_url: `${window.location.origin}/billing/authorization_status`,
            },
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
                Your card will not be charged but we place a $0.50 hold on it to verify your card that will be released
                in 7 days.
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
            void loadStripeJs()
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
                        <div className="text-4xl">
                            <img
                                src="https://res.cloudinary.com/dmukukwp6/image/upload/loading_bdba47912e.gif"
                                alt="Loading animation"
                            />
                        </div>
                        <p className="text-secondary text-md mt-4">We're contacting the Hedgehogs for approval.</p>
                    </div>
                )}
            </div>
        </LemonModal>
    )
}
