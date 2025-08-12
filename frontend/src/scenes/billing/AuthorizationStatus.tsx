import { SpinnerOverlay } from '@posthog/lemon-ui'
import { useActions } from 'kea'

import { paymentEntryLogic } from './paymentEntryLogic'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'

// note(@zach): this page is only used when a payment method is entered into the payment entry modal
// that requires the user to be redirect to another url, this is where they get redirected back to
export const AuthorizationStatus = (): JSX.Element => {
    const { pollAuthorizationStatus } = useActions(paymentEntryLogic)
    useOnMountEffect(pollAuthorizationStatus)

    return <SpinnerOverlay sceneLevel />
}
