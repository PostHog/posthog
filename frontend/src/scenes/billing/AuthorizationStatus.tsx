import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, SpinnerOverlay } from '@posthog/lemon-ui'

import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { urls } from 'scenes/urls'

import { paymentEntryLogic } from './paymentEntryLogic'
import { PaymentCompletion } from './PaymentEntryModal'

// note(@zach): this page is only used when a payment method is entered into the payment entry modal
// that requires the user to be redirect to another url, this is where they get redirected back to
export const AuthorizationStatus = (): JSX.Element => {
    const { pollAuthorizationStatus } = useActions(paymentEntryLogic)
    const { apiError, stripeError, completedPaymentOrganization } = useValues(paymentEntryLogic)
    useOnMountEffect(pollAuthorizationStatus)

    if (completedPaymentOrganization) {
        return <PaymentCompletion />
    }
    if (apiError || stripeError) {
        return (
            <LemonBanner type="error">
                <p>{apiError || stripeError}</p>
                <LemonButton to={urls.organizationBilling()} type="primary">
                    Return to billing
                </LemonButton>
            </LemonBanner>
        )
    }
    return <SpinnerOverlay sceneLevel />
}
