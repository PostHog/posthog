import { LemonButton, LemonModal, Spinner } from '@posthog/lemon-ui'
import { Elements, PaymentElement, useElements, useStripe } from '@stripe/react-stripe-js'
import { loadStripe } from '@stripe/stripe-js'
import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { paymentEntryLogic } from './PaymentEntryLogic'

const stripePromise = loadStripe(window.STRIPE_PUBLIC_KEY!)

export const PaymentForm = (): JSX.Element => {
    const { error, isLoading } = useValues(paymentEntryLogic)
    const { setError, hidePaymentEntryModal, pollAuthorizationStatus, setLoading } = useActions(paymentEntryLogic)

    const stripe = useStripe()
    const elements = useElements()

    // @ts-expect-error
    const handleSubmit = async (event): Promise<void> => {
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
            setError(result.error.message)
        } else {
            pollAuthorizationStatus()
        }
    }

    return (
        <div>
            <PaymentElement />
            {error && <div className="error">{error}</div>}
            <div className="flex justify-end space-x-2 mt-2">
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

interface PaymentEntryModalProps {
    redirectPath?: string | null
}

export const PaymentEntryModal = ({ redirectPath = null }: PaymentEntryModalProps): JSX.Element | null => {
    const { clientSecret, paymentEntryModalOpen } = useValues(paymentEntryLogic)
    const { hidePaymentEntryModal, initiateAuthorization } = useActions(paymentEntryLogic)

    useEffect(() => {
        initiateAuthorization(redirectPath)
    }, [redirectPath])

    return (
        <LemonModal
            onClose={hidePaymentEntryModal}
            width="max(44vw)"
            isOpen={paymentEntryModalOpen}
            title="Add your payment details"
            description="Your card will not be charged."
        >
            <div>
                {clientSecret ? (
                    <Elements stripe={stripePromise} options={{ clientSecret }}>
                        <PaymentForm />
                    </Elements>
                ) : (
                    <div className="min-h-40 flex justify-center items-center">
                        <div className="text-4xl">
                            <Spinner />
                        </div>
                    </div>
                )}
            </div>
        </LemonModal>
    )
}
