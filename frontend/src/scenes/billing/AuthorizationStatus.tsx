import { SpinnerOverlay } from '@posthog/lemon-ui'
import { useActions } from 'kea'
import { useEffect } from 'react'

import { paymentEntryLogic } from './PaymentEntryLogic'

export const AuthorizationStatus = (): JSX.Element => {
    const { pollAuthorizationStatus } = useActions(paymentEntryLogic)

    useEffect(() => {
        pollAuthorizationStatus()
    }, [])

    return <SpinnerOverlay sceneLevel />
}
